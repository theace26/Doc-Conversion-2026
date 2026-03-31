"""
Caption/subtitle file parser — SRT, VTT (WebVTT), and SBV (YouTube).

Parses existing caption files into TranscriptionResult for use in the
transcription fallback chain (caption file → Whisper → cloud).

Encoding chain: UTF-8-BOM → UTF-8 → latin-1 → cp1252
(same approach as CSV handler — Windows caption tools often produce latin-1).
"""

import re

import structlog
from pathlib import Path

from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment

log = structlog.get_logger(__name__)


class CaptionIngestor:
    """Parse SRT, VTT, and SBV caption files into TranscriptionResult."""

    ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]

    @classmethod
    async def parse(cls, path: Path) -> TranscriptionResult:
        """Parse a caption file and return a TranscriptionResult."""
        ext = path.suffix.lower()
        text = cls._read_with_encoding(path)

        if ext == ".srt":
            segments = cls._parse_srt(text)
        elif ext == ".vtt":
            segments = cls._parse_vtt(text)
        elif ext == ".sbv":
            segments = cls._parse_sbv(text)
        else:
            raise ValueError(f"Unsupported caption format: {ext}")

        full_text = " ".join(s.text for s in segments)
        duration = segments[-1].end_seconds if segments else None

        log.info(
            "caption_parsed",
            file=path.name,
            format=ext,
            segments=len(segments),
            words=len(full_text.split()) if full_text else 0,
        )

        return TranscriptionResult(
            segments=segments,
            engine="caption_ingest",
            duration_seconds=duration,
            word_count=len(full_text.split()) if full_text else 0,
            raw_text=full_text,
        )

    @classmethod
    def _read_with_encoding(cls, path: Path) -> str:
        """Try multiple encodings until one works."""
        for enc in cls.ENCODINGS:
            try:
                return path.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"Cannot decode {path.name} with any supported encoding")

    @classmethod
    def _parse_srt(cls, text: str) -> list[TranscriptionSegment]:
        """
        Parse SRT format:
          1
          00:00:01,000 --> 00:00:04,000
          Hello world
          <blank line>
        """
        segments = []
        blocks = re.split(r"\n\n+", text.strip())
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # Find the timestamp line (may be line 0 or line 1)
            ts_line = None
            text_start = 0
            for i, line in enumerate(lines):
                if "-->" in line:
                    ts_line = line
                    text_start = i + 1
                    break

            if ts_line is None:
                continue

            match = re.match(
                r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
                r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})",
                ts_line,
            )
            if not match:
                continue

            start = cls._hms_to_seconds(*[int(x) for x in match.groups()[:4]])
            end = cls._hms_to_seconds(*[int(x) for x in match.groups()[4:]])
            content = " ".join(lines[text_start:]).strip()
            # Strip HTML tags (some SRT files have <i>, <b>, etc.)
            content = re.sub(r"<[^>]+>", "", content)

            if content:
                segments.append(
                    TranscriptionSegment(
                        index=len(segments),
                        start_seconds=start,
                        end_seconds=end,
                        text=content,
                    )
                )

        return segments

    @classmethod
    def _parse_vtt(cls, text: str) -> list[TranscriptionSegment]:
        """
        Parse WebVTT format. Similar to SRT but with WEBVTT header
        and dots instead of commas in timestamps.
        """
        # Remove WEBVTT header and any metadata blocks
        if text.startswith("WEBVTT"):
            # Skip past the header block
            parts = text.split("\n\n", 1)
            text = parts[1] if len(parts) > 1 else ""
        return cls._parse_srt(text)

    @classmethod
    def _parse_sbv(cls, text: str) -> list[TranscriptionSegment]:
        """
        Parse SBV (YouTube) format:
          0:00:01.000,0:00:04.000
          Hello world
          <blank line>
        """
        segments = []
        blocks = re.split(r"\n\n+", text.strip())
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue
            match = re.match(
                r"(\d+):(\d{2}):(\d{2})\.(\d{3}),(\d+):(\d{2}):(\d{2})\.(\d{3})",
                lines[0],
            )
            if not match:
                continue
            start = cls._hms_to_seconds(*[int(x) for x in match.groups()[:4]])
            end = cls._hms_to_seconds(*[int(x) for x in match.groups()[4:]])
            content = " ".join(lines[1:]).strip()

            if content:
                segments.append(
                    TranscriptionSegment(
                        index=len(segments),
                        start_seconds=start,
                        end_seconds=end,
                        text=content,
                    )
                )

        return segments

    @staticmethod
    def _hms_to_seconds(h: int, m: int, s: int, ms: int) -> float:
        """Convert hours, minutes, seconds, milliseconds to total seconds."""
        return h * 3600 + m * 60 + s + ms / 1000.0
