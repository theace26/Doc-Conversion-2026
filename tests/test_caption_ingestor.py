"""
Tests for core/caption_ingestor.py — SRT, VTT, and SBV parsing.
"""

from pathlib import Path

import pytest

from core.caption_ingestor import CaptionIngestor


# ── SRT tests ────────────────────────────────────────────────────────────────


async def test_parse_srt(tmp_path):
    """Parse a valid SRT file."""
    srt_content = """\
1
00:00:01,000 --> 00:00:04,000
Hello world

2
00:00:05,500 --> 00:00:08,200
This is a test subtitle

3
00:00:10,000 --> 00:00:15,000
Third segment here
"""
    path = tmp_path / "test.srt"
    path.write_text(srt_content, encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert result.engine == "caption_ingest"
    assert len(result.segments) == 3
    assert result.segments[0].text == "Hello world"
    assert result.segments[0].start_seconds == 1.0
    assert result.segments[0].end_seconds == 4.0
    assert result.segments[1].text == "This is a test subtitle"
    assert result.segments[1].start_seconds == 5.5
    assert result.segments[2].text == "Third segment here"
    assert result.word_count > 0
    assert result.duration_seconds == 15.0


async def test_parse_srt_strips_html_tags(tmp_path):
    """HTML tags in SRT segments should be stripped."""
    srt_content = """\
1
00:00:01,000 --> 00:00:04,000
<i>Italic text</i> and <b>bold</b>
"""
    path = tmp_path / "tags.srt"
    path.write_text(srt_content, encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert len(result.segments) == 1
    assert result.segments[0].text == "Italic text and bold"


async def test_parse_srt_multiline_text(tmp_path):
    """Multi-line text in a single SRT block should be joined."""
    srt_content = """\
1
00:00:01,000 --> 00:00:04,000
First line
Second line
"""
    path = tmp_path / "multiline.srt"
    path.write_text(srt_content, encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert len(result.segments) == 1
    assert result.segments[0].text == "First line Second line"


# ── VTT tests ────────────────────────────────────────────────────────────────


async def test_parse_vtt(tmp_path):
    """Parse a valid WebVTT file."""
    vtt_content = """\
WEBVTT

00:00:01.000 --> 00:00:04.000
Hello from VTT

00:00:05.000 --> 00:00:08.000
Second cue
"""
    path = tmp_path / "test.vtt"
    path.write_text(vtt_content, encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert result.engine == "caption_ingest"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello from VTT"
    assert result.segments[0].start_seconds == 1.0
    assert result.segments[1].text == "Second cue"


async def test_parse_vtt_with_metadata(tmp_path):
    """VTT with header metadata should still parse cues correctly."""
    vtt_content = """\
WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:04.000
First cue

00:00:05.000 --> 00:00:08.000
Second cue
"""
    path = tmp_path / "meta.vtt"
    path.write_text(vtt_content, encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert len(result.segments) == 2


# ── SBV tests ────────────────────────────────────────────────────────────────


async def test_parse_sbv(tmp_path):
    """Parse a valid SBV (YouTube) file."""
    sbv_content = """\
0:00:01.000,0:00:04.000
Hello from SBV

0:00:05.500,0:00:08.200
Second block
"""
    path = tmp_path / "test.sbv"
    path.write_text(sbv_content, encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert result.engine == "caption_ingest"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello from SBV"
    assert result.segments[0].start_seconds == 1.0
    assert result.segments[0].end_seconds == 4.0


# ── Encoding tests ───────────────────────────────────────────────────────────


async def test_parse_latin1_encoding(tmp_path):
    """Caption file in latin-1 encoding should be decoded correctly."""
    srt_content = "1\n00:00:01,000 --> 00:00:04,000\nCaf\xe9 au lait\n"
    path = tmp_path / "latin1.srt"
    path.write_bytes(srt_content.encode("latin-1"))

    result = await CaptionIngestor.parse(path)

    assert len(result.segments) == 1
    assert "Caf" in result.segments[0].text


async def test_parse_utf8_bom(tmp_path):
    """Caption file with UTF-8 BOM should parse correctly."""
    srt_content = "1\n00:00:01,000 --> 00:00:04,000\nHello BOM\n"
    path = tmp_path / "bom.srt"
    path.write_bytes(b"\xef\xbb\xbf" + srt_content.encode("utf-8"))

    result = await CaptionIngestor.parse(path)

    assert len(result.segments) == 1
    assert result.segments[0].text == "Hello BOM"


# ── Edge cases ───────────────────────────────────────────────────────────────


async def test_parse_empty_srt(tmp_path):
    """Empty SRT file should return zero segments."""
    path = tmp_path / "empty.srt"
    path.write_text("", encoding="utf-8")

    result = await CaptionIngestor.parse(path)

    assert len(result.segments) == 0
    assert result.word_count == 0


async def test_parse_unsupported_format(tmp_path):
    """Unsupported extension should raise ValueError."""
    path = tmp_path / "test.ass"
    path.write_text("some content", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported caption format"):
        await CaptionIngestor.parse(path)


async def test_hms_to_seconds():
    """Verify time conversion helper."""
    assert CaptionIngestor._hms_to_seconds(1, 30, 45, 500) == 5445.5
    assert CaptionIngestor._hms_to_seconds(0, 0, 0, 0) == 0.0
    assert CaptionIngestor._hms_to_seconds(0, 0, 1, 0) == 1.0
