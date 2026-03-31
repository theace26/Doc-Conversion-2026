"""
Audio format handler — .mp3, .wav, .flac, .ogg, .m4a, .wma, .aac, .webm (audio).

Ingest: Runs the media transcription pipeline (MediaOrchestrator) and returns
a DocumentModel containing the transcript as Markdown elements.

Export: Not supported — audio files cannot be reconstructed from text.
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
class AudioHandler(FormatHandler):
    """Format handler for audio files (.mp3, .wav, .flac, etc.)."""

    EXTENSIONS = [
        "mp3", "wav", "flac", "ogg", "m4a", "wma", "aac",
    ]

    def ingest(self, file_path: Path, **kwargs) -> DocumentModel:
        """
        Transcribe an audio file and return a DocumentModel.

        Runs the async MediaOrchestrator synchronously via asyncio.to_thread
        since FormatHandler.ingest() is synchronous.
        """
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="audio")

        # Run async orchestrator from sync context
        result = _run_media_conversion(file_path)

        # Build DocumentModel from transcription result
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
        meta_lines = [
            f"**Duration:** {result.probe.duration_secs:.1f}s" if result.probe.duration_secs else "",
            f"**Engine:** {tr.engine}",
            f"**Language:** {tr.language}" if tr.language else "",
            f"**Words:** {tr.word_count}",
        ]
        meta_text = "  \n".join(line for line in meta_lines if line)
        model.add_element(
            Element(type=ElementType.PARAGRAPH, content=meta_text)
        )

        # Add transcript heading
        model.add_element(
            Element(type=ElementType.HEADING, content="Transcript", level=2)
        )

        # Add each segment as a paragraph with timestamp
        from core.transcript_formatter import TranscriptFormatter

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
        """Audio export is not supported."""
        raise NotImplementedError(
            "Audio files cannot be reconstructed from text. "
            "Use TranscriptFormatter for .srt/.vtt output."
        )

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """No style data for audio files."""
        return {}


def _run_media_conversion(file_path: Path):
    """Run MediaOrchestrator.convert() from a synchronous context."""
    from core.media_orchestrator import MediaOrchestrator

    async def _convert():
        from core.database import get_all_preferences

        preferences = await get_all_preferences()
        output_dir = file_path.parent / "_markflow"
        return await MediaOrchestrator.convert(file_path, output_dir, preferences)

    # If there's already a running event loop (called from bulk worker),
    # create a new one in a thread. Otherwise, run directly.
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
