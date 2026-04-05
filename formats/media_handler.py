"""
Media (video) format handler — .mp4, .mov, .avi, .mkv, .wmv, .m4v, .webm.

Ingest: Runs the media transcription pipeline (MediaOrchestrator) and returns
a DocumentModel containing the transcript + optional scene descriptions as
Markdown elements.

Export: Not supported — video files cannot be reconstructed from text.
"""

import asyncio
import time
from pathlib import Path
from typing import Any

import structlog

from core.document_model import (
    DocumentMetadata,
    DocumentModel,
    Element,
    ElementType,
)
from formats.base import FormatHandler, register_handler

log = structlog.get_logger(__name__)


@register_handler
class MediaHandler(FormatHandler):
    """Format handler for video files (.mp4, .mov, .mkv, etc.)."""

    EXTENSIONS = [
        "mp4", "mov", "avi", "mkv", "wmv", "m4v", "webm",
    ]

    def ingest(self, file_path: Path, **kwargs) -> DocumentModel:
        """
        Transcribe a video file and return a DocumentModel.

        Runs the async MediaOrchestrator synchronously since
        FormatHandler.ingest() is synchronous.
        """
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="video")

        # Run async orchestrator from sync context
        result = _run_media_conversion(file_path)

        # Build DocumentModel from transcription + optional scene descriptions
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=file_path.suffix.lstrip("."),
            title=file_path.stem,
        )

        # Add title heading
        model.add_element(
            Element(type=ElementType.HEADING, content=file_path.stem, level=1)
        )

        # Add metadata paragraph
        tr = result.transcription
        probe = result.probe
        meta_lines = [
            f"**Duration:** {probe.duration_secs:.1f}s" if probe.duration_secs else "",
            f"**Resolution:** {probe.width}x{probe.height}" if probe.width and probe.height else "",
            f"**Engine:** {tr.engine}",
            f"**Language:** {tr.language}" if tr.language else "",
            f"**Words:** {tr.word_count}",
        ]
        if result.scenes:
            meta_lines.append(f"**Scenes:** {len(result.scenes)}")
        meta_text = "  \n".join(line for line in meta_lines if line)
        model.add_element(
            Element(type=ElementType.PARAGRAPH, content=meta_text)
        )

        # Add transcript heading
        model.add_element(
            Element(type=ElementType.HEADING, content="Transcript", level=2)
        )

        # Add segments with optional interleaved scene descriptions
        from core.transcript_formatter import TranscriptFormatter

        if result.scenes:
            scene_iter = iter(
                sorted(result.scenes, key=lambda s: s.start_seconds)
            )
            next_scene = next(scene_iter, None)

            for seg in tr.segments:
                # Insert scene breaks before this segment
                while next_scene and next_scene.start_seconds <= seg.start_seconds:
                    ts_s = TranscriptFormatter.format_timestamp(
                        next_scene.start_seconds
                    )
                    ts_e = TranscriptFormatter.format_timestamp(
                        next_scene.end_seconds
                    )
                    scene_text = (
                        f"**[Scene {next_scene.scene_index + 1} "
                        f"\u2014 {ts_s} to {ts_e}]**"
                    )
                    if next_scene.description:
                        scene_text += f"\n*{next_scene.description}*"
                    model.add_element(Element(type=ElementType.HORIZONTAL_RULE))
                    model.add_element(
                        Element(type=ElementType.PARAGRAPH, content=scene_text)
                    )
                    model.add_element(Element(type=ElementType.HORIZONTAL_RULE))
                    next_scene = next(scene_iter, None)

                ts = TranscriptFormatter.format_timestamp(seg.start_seconds)
                speaker = f"**{seg.speaker}:** " if seg.speaker else ""
                model.add_element(
                    Element(
                        type=ElementType.PARAGRAPH,
                        content=f"[{ts}] {speaker}{seg.text}",
                    )
                )

            # Remaining scenes
            while next_scene:
                ts_s = TranscriptFormatter.format_timestamp(
                    next_scene.start_seconds
                )
                ts_e = TranscriptFormatter.format_timestamp(next_scene.end_seconds)
                scene_text = (
                    f"**[Scene {next_scene.scene_index + 1} "
                    f"\u2014 {ts_s} to {ts_e}]**"
                )
                if next_scene.description:
                    scene_text += f"\n*{next_scene.description}*"
                model.add_element(Element(type=ElementType.HORIZONTAL_RULE))
                model.add_element(
                    Element(type=ElementType.PARAGRAPH, content=scene_text)
                )
                model.add_element(Element(type=ElementType.HORIZONTAL_RULE))
                next_scene = next(scene_iter, None)
        else:
            for seg in tr.segments:
                ts = TranscriptFormatter.format_timestamp(seg.start_seconds)
                speaker = f"**{seg.speaker}:** " if seg.speaker else ""
                model.add_element(
                    Element(
                        type=ElementType.PARAGRAPH,
                        content=f"[{ts}] {speaker}{seg.text}",
                    )
                )

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            segments=len(tr.segments),
            words=tr.word_count,
            scenes=len(result.scenes) if result.scenes else 0,
            duration_ms=duration_ms,
        )
        return model

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        """Video export is not supported."""
        raise NotImplementedError(
            "Video files cannot be reconstructed from text. "
            "Use TranscriptFormatter for .srt/.vtt output."
        )

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """No style data for video files."""
        return {}


def _run_media_conversion(file_path: Path):
    """Run MediaOrchestrator.convert() from a synchronous context."""
    import tempfile
    from core.media_orchestrator import MediaOrchestrator

    async def _convert():
        from core.database import get_all_preferences

        preferences = await get_all_preferences()
        # Use a temp dir for orchestrator output — the source mount may be
        # read-only (/mnt/source).  The bulk worker places the final .md and
        # sidecar in the correct output tree independently.
        output_dir = Path(tempfile.mkdtemp(prefix="markflow_media_"))
        return await MediaOrchestrator.convert(file_path, output_dir, preferences)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _convert())
            return future.result()
    else:
        return asyncio.run(_convert())
