"""
Media probe — ffprobe wrapper for codec detection, duration, and transcode decisions.

Single source of truth for "what is this media file" — determines whether audio
needs transcoding before Whisper can process it.
"""

import asyncio
import json

import structlog
from dataclasses import dataclass
from pathlib import Path

log = structlog.get_logger(__name__)


@dataclass
class MediaProbeResult:
    """Parsed ffprobe output with transcode decision."""

    path: Path
    container: str  # e.g. "mov,mp4,m4a,3gp,3g2,mj2"
    media_type: str  # "video" or "audio"
    has_video: bool
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None
    audio_channels: int | None
    audio_sample_rate: int | None
    duration_secs: float | None
    width: int | None
    height: int | None
    frame_rate: float | None
    needs_transcode: bool  # True if Whisper can't read this directly
    transcode_reason: str | None


class MediaProbeError(Exception):
    """Raised when ffprobe or ffmpeg fails."""


class MediaProbe:
    """ffprobe wrapper with transcode decision logic."""

    # Codecs Whisper can read natively (via ffmpeg's built-in decoders)
    WHISPER_NATIVE_AUDIO = {
        "mp3", "aac", "flac", "vorbis", "opus",
        "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le",
    }

    @staticmethod
    async def probe(path: Path) -> MediaProbeResult:
        """Run ffprobe, parse JSON output, determine transcode needs."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise MediaProbeError(
                f"ffprobe failed for {path.name}: {stderr.decode()[:500]}"
            )

        data = json.loads(stdout.decode())
        streams = data.get("streams", [])
        fmt = data.get("format", {})

        # Separate video and audio streams (skip album art)
        video_stream = None
        audio_stream = None
        for s in streams:
            codec_type = s.get("codec_type")
            if codec_type == "video":
                # Skip album art / attached pictures
                disposition = s.get("disposition", {})
                if disposition.get("attached_pic", 0) == 1:
                    continue
                if video_stream is None:
                    video_stream = s
            elif codec_type == "audio":
                if audio_stream is None:
                    audio_stream = s

        has_video = video_stream is not None
        has_audio = audio_stream is not None

        # Extract video info
        video_codec = video_stream.get("codec_name") if video_stream else None
        width = int(video_stream["width"]) if video_stream and "width" in video_stream else None
        height = int(video_stream["height"]) if video_stream and "height" in video_stream else None
        frame_rate = _parse_frame_rate(video_stream.get("r_frame_rate")) if video_stream else None

        # Extract audio info
        audio_codec = audio_stream.get("codec_name") if audio_stream else None
        audio_channels = int(audio_stream["channels"]) if audio_stream and "channels" in audio_stream else None
        audio_sample_rate = int(audio_stream["sample_rate"]) if audio_stream and "sample_rate" in audio_stream else None

        # Duration: prefer format-level, fall back to stream
        duration_secs = None
        if "duration" in fmt:
            duration_secs = float(fmt["duration"])
        elif audio_stream and "duration" in audio_stream:
            duration_secs = float(audio_stream["duration"])
        elif video_stream and "duration" in video_stream:
            duration_secs = float(video_stream["duration"])

        # Container format
        container = fmt.get("format_name", "unknown")

        # Determine media type
        media_type = "video" if has_video else "audio"

        # Transcode decision
        needs_transcode = True
        transcode_reason = None
        if not has_audio:
            needs_transcode = False
            transcode_reason = "no_audio"
        elif has_video:
            needs_transcode = True
            transcode_reason = "video_file_needs_audio_extraction"
        elif audio_codec and audio_codec in MediaProbe.WHISPER_NATIVE_AUDIO:
            needs_transcode = False
            transcode_reason = None
        else:
            needs_transcode = True
            transcode_reason = f"audio_codec_{audio_codec}_not_whisper_native"

        result = MediaProbeResult(
            path=path,
            container=container,
            media_type=media_type,
            has_video=has_video,
            has_audio=has_audio,
            video_codec=video_codec,
            audio_codec=audio_codec,
            audio_channels=audio_channels,
            audio_sample_rate=audio_sample_rate,
            duration_secs=duration_secs,
            width=width,
            height=height,
            frame_rate=frame_rate,
            needs_transcode=needs_transcode,
            transcode_reason=transcode_reason,
        )

        log.info(
            "media_probe_complete",
            file=path.name,
            type=media_type,
            duration=duration_secs,
            audio_codec=audio_codec,
            video_codec=video_codec,
            needs_transcode=needs_transcode,
        )
        return result

    @staticmethod
    async def extract_audio_for_whisper(
        source: Path,
        dest: Path,
        probe: MediaProbeResult,
    ) -> Path:
        """
        Extract and convert audio to 16kHz mono WAV for Whisper.
        If audio codec is Whisper-native AND file is audio-only, return source path.
        Otherwise, run ffmpeg to produce dest (WAV).
        """
        if not probe.needs_transcode and probe.media_type == "audio":
            return source

        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-vn",                   # drop video
            "-acodec", "pcm_s16le",  # 16-bit PCM
            "-ar", "16000",          # 16kHz
            "-ac", "1",              # mono
            str(dest),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise MediaProbeError(
                f"ffmpeg audio extraction failed for {source.name}: "
                f"{stderr.decode()[:500]}"
            )

        log.info(
            "audio_extracted_for_whisper",
            source=source.name,
            dest=str(dest),
            duration=probe.duration_secs,
        )
        return dest


def _parse_frame_rate(rate_str: str | None) -> float | None:
    """Parse ffprobe r_frame_rate fraction (e.g. '30000/1001') to float."""
    if not rate_str:
        return None
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/")
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(rate_str)
    except (ValueError, ZeroDivisionError):
        return None
