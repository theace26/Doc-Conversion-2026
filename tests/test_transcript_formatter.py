"""
Tests for core/transcript_formatter.py — output formatting (.md, .srt, .vtt).
"""

from pathlib import Path

import pytest

from core.transcript_formatter import (
    FormatterOutput,
    SceneDescription,
    TranscriptFormatter,
)
from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_transcription():
    """TranscriptionResult with 3 segments."""
    return TranscriptionResult(
        segments=[
            TranscriptionSegment(
                index=0, start_seconds=0.0, end_seconds=3.5, text="Hello everyone"
            ),
            TranscriptionSegment(
                index=1, start_seconds=3.5, end_seconds=7.0, text="Welcome to the show"
            ),
            TranscriptionSegment(
                index=2, start_seconds=7.0, end_seconds=12.0, text="Let us begin"
            ),
        ],
        language="en",
        duration_seconds=12.0,
        engine="whisper_local",
        model_name="base",
        word_count=9,
        raw_text="Hello everyone Welcome to the show Let us begin",
    )


@pytest.fixture
def sample_scenes():
    """Scene descriptions for interleaving."""
    return [
        SceneDescription(
            scene_index=0,
            start_seconds=0.0,
            end_seconds=5.0,
            description="Opening title card",
        ),
        SceneDescription(
            scene_index=1,
            start_seconds=5.0,
            end_seconds=12.0,
            description="Speaker at podium",
        ),
    ]


# ── Timestamp formatting ────────────────────────────────────────────────────


def test_format_timestamp():
    assert TranscriptFormatter.format_timestamp(0) == "00:00:00"
    assert TranscriptFormatter.format_timestamp(61) == "00:01:01"
    assert TranscriptFormatter.format_timestamp(3661) == "01:01:01"
    assert TranscriptFormatter.format_timestamp(3723) == "01:02:03"


def test_format_srt_timestamp():
    assert TranscriptFormatter.format_srt_timestamp(0) == "00:00:00,000"
    assert TranscriptFormatter.format_srt_timestamp(1.5) == "00:00:01,500"
    assert TranscriptFormatter.format_srt_timestamp(3661.123) == "01:01:01,123"


def test_format_vtt_timestamp():
    assert TranscriptFormatter.format_vtt_timestamp(0) == "00:00:00.000"
    assert TranscriptFormatter.format_vtt_timestamp(1.5) == "00:00:01.500"
    assert TranscriptFormatter.format_vtt_timestamp(3661.123) == "01:01:01.123"


# ── MD output ────────────────────────────────────────────────────────────────


def test_format_md_basic(tmp_path, sample_transcription):
    """Verify .md output structure: frontmatter + heading + segments."""
    output = TranscriptFormatter.format_all(
        transcription=sample_transcription,
        output_dir=tmp_path,
        filename_stem="test_video",
        source_format="mp4",
    )

    assert output.md_path.exists()
    md = output.md_content

    # Frontmatter
    assert md.startswith("---")
    assert 'title: "test_video"' in md
    assert "source_format: mp4" in md
    assert "engine: whisper_local" in md
    assert "whisper_model: base" in md
    assert "language: en" in md
    assert "word_count: 9" in md

    # Content
    assert "# test_video" in md
    assert "## Transcript" in md
    assert "[00:00:00] Hello everyone" in md
    assert "[00:00:03] Welcome to the show" in md
    assert "[00:00:07] Let us begin" in md


def test_format_md_with_source_path(tmp_path, sample_transcription):
    """source_path should appear in frontmatter when provided."""
    output = TranscriptFormatter.format_all(
        transcription=sample_transcription,
        output_dir=tmp_path,
        filename_stem="test",
        source_format="mp3",
        source_path="/mnt/source/audio/test.mp3",
    )
    assert 'source_path: "/mnt/source/audio/test.mp3"' in output.md_content


def test_format_md_with_speaker(tmp_path):
    """Speaker names should be rendered in bold."""
    tr = TranscriptionResult(
        segments=[
            TranscriptionSegment(
                index=0, start_seconds=0, end_seconds=3,
                text="Hello", speaker="Alice",
            ),
        ],
        engine="whisper_local",
        word_count=1,
        raw_text="Hello",
    )

    output = TranscriptFormatter.format_all(
        tr, tmp_path, "test", "mp3"
    )
    assert "**Alice:**" in output.md_content


# ── SRT output ───────────────────────────────────────────────────────────────


def test_format_srt(tmp_path, sample_transcription):
    """Verify .srt output format."""
    output = TranscriptFormatter.format_all(
        sample_transcription, tmp_path, "test", "mp4"
    )

    assert output.srt_path.exists()
    srt = output.srt_path.read_text()

    # First segment
    assert "1\n" in srt
    assert "00:00:00,000 --> 00:00:03,500" in srt
    assert "Hello everyone" in srt

    # Second segment
    assert "2\n" in srt
    assert "00:00:03,500 --> 00:00:07,000" in srt
    assert "Welcome to the show" in srt

    # Third segment
    assert "3\n" in srt


# ── VTT output ───────────────────────────────────────────────────────────────


def test_format_vtt(tmp_path, sample_transcription):
    """Verify .vtt output format."""
    output = TranscriptFormatter.format_all(
        sample_transcription, tmp_path, "test", "mp4"
    )

    assert output.vtt_path.exists()
    vtt = output.vtt_path.read_text()

    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:03.500" in vtt
    assert "Hello everyone" in vtt
    # VTT uses dots not commas
    assert "," not in vtt.split("WEBVTT")[1].split("-->")[0]


# ── Scene interleaving ───────────────────────────────────────────────────────


def test_format_md_with_scenes(tmp_path, sample_transcription, sample_scenes):
    """Scene descriptions should be interleaved in .md output."""
    output = TranscriptFormatter.format_all(
        transcription=sample_transcription,
        output_dir=tmp_path,
        filename_stem="test",
        source_format="mp4",
        scenes=sample_scenes,
    )

    md = output.md_content
    assert "**[Scene 1" in md
    assert "Opening title card" in md
    assert "**[Scene 2" in md
    assert "Speaker at podium" in md
    # Scenes should appear before corresponding segments
    scene1_pos = md.index("Scene 1")
    hello_pos = md.index("Hello everyone")
    assert scene1_pos < hello_pos


def test_scenes_without_description(tmp_path, sample_transcription):
    """Scene without description should still render the header."""
    scenes = [
        SceneDescription(
            scene_index=0, start_seconds=0, end_seconds=5, description=None
        ),
    ]

    output = TranscriptFormatter.format_all(
        sample_transcription, tmp_path, "test", "mp4", scenes=scenes
    )

    assert "**[Scene 1" in output.md_content


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_format_empty_transcription(tmp_path):
    """Empty transcription should produce valid but minimal output."""
    tr = TranscriptionResult(
        segments=[], engine="whisper_local", word_count=0, raw_text=""
    )

    output = TranscriptFormatter.format_all(tr, tmp_path, "empty", "mp3")

    assert output.md_path.exists()
    assert output.srt_path.exists()
    assert output.vtt_path.exists()
    assert "# empty" in output.md_content
    assert output.srt_path.read_text().strip() == ""
    assert output.vtt_path.read_text().strip() == "WEBVTT"


def test_format_all_creates_output_dir(tmp_path, sample_transcription):
    """Output dir should be created if it doesn't exist."""
    output_dir = tmp_path / "nested" / "output"
    # format_all doesn't create dirs — the orchestrator does.
    # But the files should be writable if the dir exists.
    output_dir.mkdir(parents=True)

    output = TranscriptFormatter.format_all(
        sample_transcription, output_dir, "test", "mp4"
    )

    assert output.md_path.parent == output_dir


def test_format_all_returns_correct_paths(tmp_path, sample_transcription):
    """FormatterOutput should contain correct file paths."""
    output = TranscriptFormatter.format_all(
        sample_transcription, tmp_path, "myfile", "wav"
    )

    assert isinstance(output, FormatterOutput)
    assert output.md_path == tmp_path / "myfile.md"
    assert output.srt_path == tmp_path / "myfile.srt"
    assert output.vtt_path == tmp_path / "myfile.vtt"
