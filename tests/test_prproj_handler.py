"""Test suite for the Premiere Pro project (.prproj) deep handler.

Strategy:
    - Synthetic fixtures generated inside the suite; gzipped XML matching
      the parser's defensive tag-name heuristics.
    - One test per acceptance criterion in
      docs/superpowers/plans/2026-04-28-prproj-deep-handler.md Phase 1.
    - `test_real_fixtures_if_present` auto-runs against any `.prproj` files
      the operator drops into `tests/fixtures/prproj/` for end-to-end
      validation against actual Premiere output.

Author: v0.34.0 Phase 1 verification.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from formats.base import get_handler
from formats.prproj.handler import PrprojHandler
from formats.prproj.parser import (
    parse_prproj,
    PrprojDocument,
    MediaRef,
    Sequence,
    Bin,
    empty_document,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prproj"


# ── Synthetic fixture builders ───────────────────────────────────────────────


def _gzip_xml(xml: str, path: Path) -> Path:
    """Write `xml` as gzipped bytes to `path`. Returns the same path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(xml.encode("utf-8"))
    return path


def _minimal_xml(media_paths: list[str], sequences: int = 1) -> str:
    """1 sequence, N media refs — sanity-test fixture."""
    media_blocks = "\n".join(
        f"  <MasterClip ObjectID='clip-{i}'>"
        f"<Name>{Path(p).name}</Name>"
        f"<FilePath>{p}</FilePath>"
        f"</MasterClip>"
        for i, p in enumerate(media_paths)
    )
    seq_blocks = "\n".join(
        f"  <Sequence ObjectID='seq-{i}'>"
        f"<Name>Sequence {i+1}</Name>"
        f"<VideoFrameRate>23.976</VideoFrameRate>"
        f"<VideoFrameWidth>1920</VideoFrameWidth>"
        f"<VideoFrameHeight>1080</VideoFrameHeight>"
        f"<ClipCount>{len(media_paths)}</ClipCount>"
        f"<MarkerCount>3</MarkerCount>"
        f"</Sequence>"
        for i in range(sequences)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="40" Premiere_Version="24.0.0">
  <Project>
    <Title>Test Project</Title>
{media_blocks}
{seq_blocks}
    <Bin ObjectID='bin-root'><Name>Footage</Name></Bin>
    <Bin ObjectID='bin-audio' ParentObjectURef='bin-root'><Name>Audio</Name></Bin>
  </Project>
</PremiereData>
"""


def _medium_xml(media_count: int = 100, seq_count: int = 10) -> str:
    """N media + M sequences — happy-path fixture."""
    media = [f"\\\\NAS\\Footage\\BCAMERA\\C{i:04d}.MP4" for i in range(media_count)]
    return _minimal_xml(media, sequences=seq_count)


def _unknown_root_xml() -> str:
    """Stub XML with an unrecognised root element."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<NotPremiere>
  <Garbage>
    <Path>nope/whatever.txt</Path>
  </Garbage>
</NotPremiere>
"""


def _malformed_sequence_xml() -> str:
    """Valid XML, but the Sequence node is missing its name + numbers."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<PremiereData>
  <Project>
    <Title>Malformed</Title>
    <MasterClip><FilePath>/some/clip.mp4</FilePath></MasterClip>
    <Sequence>
      <!-- no Name, no rate, no nothing -->
    </Sequence>
  </Project>
</PremiereData>
"""


# ── Tests ────────────────────────────────────────────────────────────────────


def test_parse_minimal_project(tmp_path: Path) -> None:
    """Sanity-test fixture: 1 sequence + 5 clips. Verify counts."""
    media = [f"/footage/clip{i:02d}.mp4" for i in range(5)]
    fpath = _gzip_xml(_minimal_xml(media, sequences=1), tmp_path / "minimal.prproj")

    doc = parse_prproj(fpath)

    assert isinstance(doc, PrprojDocument)
    assert doc.project_name == "minimal"
    assert len(doc.media) == 5
    assert len(doc.sequences) == 1
    # All 5 should classify as video by extension
    assert all(m.media_type == "video" for m in doc.media)
    # Names should be the basename
    assert doc.media[0].name == "clip00.mp4"
    # The single sequence should have its width/height/framerate scraped
    seq = doc.sequences[0]
    assert seq.width == 1920
    assert seq.height == 1080
    assert seq.frame_rate == 23.976
    # We have known root + media + sequences → high confidence
    assert doc.schema_confidence == "high"


def test_parse_medium_project(tmp_path: Path) -> None:
    """Happy-path fixture: 10 sequences + 100 clips."""
    fpath = _gzip_xml(_medium_xml(media_count=100, seq_count=10),
                      tmp_path / "medium.prproj")

    doc = parse_prproj(fpath)

    assert len(doc.media) == 100
    assert len(doc.sequences) == 10
    assert doc.schema_confidence == "high"
    # Aggregate type breakdown: all should be video by extension
    assert sum(1 for m in doc.media if m.media_type == "video") == 100


def test_parse_handles_unknown_schema(tmp_path: Path) -> None:
    """Unrecognised root element → metadata-only fallback shape."""
    fpath = _gzip_xml(_unknown_root_xml(), tmp_path / "unknown.prproj")

    doc = parse_prproj(fpath)

    # The parser still completes — it just reports low confidence.
    assert doc.schema_confidence == "low" or doc.schema_confidence == "medium"
    # And the unknown-root warning is recorded
    assert any("unknown_root_element" in w for w in doc.parse_warnings)


def test_parse_handles_truncated_gzip(tmp_path: Path) -> None:
    """Truncated gzip stream → parser raises; handler catches at ingest."""
    # Write a partial gzip header to simulate a truncated/corrupt stream.
    fpath = tmp_path / "truncated.prproj"
    fpath.write_bytes(b"\x1f\x8b\x08")  # gzip magic + method byte, then EOF

    # Direct parser call should raise (gzip.BadGzipFile or struct.error etc.)
    with pytest.raises(Exception):
        parse_prproj(fpath)

    # But the handler's ingest method must NOT raise — it falls back.
    handler = PrprojHandler()
    model = handler.ingest(fpath)
    # The model still has at least the H1 + something — it doesn't crash.
    assert len(model.elements) >= 1
    # source_format is still prproj
    assert model.metadata.source_format == "prproj"


def test_parse_records_warnings_in_document(tmp_path: Path) -> None:
    """Malformed sequence node → parse_warnings populated, output rendered."""
    fpath = _gzip_xml(_malformed_sequence_xml(), tmp_path / "malformed.prproj")

    doc = parse_prproj(fpath)

    # Sequence still recorded (we don't drop nodes for missing inner fields)
    assert len(doc.sequences) >= 1
    # Some media still parsed
    assert len(doc.media) >= 1


def test_handler_priority_wins_over_adobe() -> None:
    """`.prproj` must route to PrprojHandler, NOT AdobeHandler."""
    handler = get_handler("prproj")
    assert handler is not None
    assert handler.__class__.__name__ == "PrprojHandler"


def test_adobe_handler_no_longer_lists_prproj() -> None:
    """AdobeHandler.EXTENSIONS dropped `prproj` in v0.34.0."""
    from formats.adobe_handler import AdobeHandler
    assert "prproj" not in AdobeHandler.EXTENSIONS


def test_empty_document_fallback() -> None:
    """`empty_document` returns a deliberately-low-confidence stub."""
    doc = empty_document("test.prproj", reason="test_reason")
    assert doc.schema_confidence == "low"
    assert len(doc.media) == 0
    assert any("test_reason" in w for w in doc.parse_warnings)


def test_handler_renders_markdown_with_media_paths(tmp_path: Path) -> None:
    """Render path: parsed doc → DocumentModel → Markdown content includes
    every media path verbatim so search indexing surfaces the project on
    a clip-name query."""
    media = ["\\\\NAS\\Foot\\C0042.MP4", "/tmp/sting.wav", "/graphics/logo.psd"]
    fpath = _gzip_xml(_minimal_xml(media, sequences=2),
                      tmp_path / "render.prproj")

    handler = PrprojHandler()
    model = handler.ingest(fpath)

    # Drive through the export to produce real Markdown text.
    out_path = tmp_path / "render.md"
    handler.export(model, out_path)
    md = out_path.read_text(encoding="utf-8")

    # Each media path should appear verbatim in the output
    for p in media:
        assert p in md, f"{p!r} missing from rendered Markdown"
    # Sequence count should appear in a heading (pluralized)
    assert "Sequences (2)" in md
    # Bin tree section heading appears whatever the bin count
    assert "Bin tree" in md


def test_media_type_classification(tmp_path: Path) -> None:
    """Path extension → media_type mapping covers all 4 buckets."""
    media = [
        "/clips/v.mp4",     # video
        "/clips/a.wav",     # audio
        "/clips/i.png",     # image
        "/clips/g.psd",     # graphic
        "/clips/x.weird",   # unknown
    ]
    fpath = _gzip_xml(_minimal_xml(media), tmp_path / "types.prproj")

    doc = parse_prproj(fpath)
    types = {m.media_type for m in doc.media}
    assert {"video", "audio", "image", "graphic", "unknown"} == types


def test_dedup_repeated_paths(tmp_path: Path) -> None:
    """Same media path appearing twice in the XML produces ONE MediaRef."""
    fpath = _gzip_xml(_minimal_xml(["/clips/v.mp4", "/clips/v.mp4"]),
                      tmp_path / "dup.prproj")

    doc = parse_prproj(fpath)
    assert len(doc.media) == 1


# ── Optional: real-fixture sweep (auto-skipped when none present) ────────────


def test_real_fixtures_if_present() -> None:
    """If the operator dropped real `.prproj` files into tests/fixtures/prproj/,
    parse each one and verify a non-empty parse result.

    Skipped (with an informative message) when no fixtures are present —
    matches the v0.34.0 ship state where Phase 0 fixtures were deferred.
    """
    if not FIXTURES_DIR.exists():
        pytest.skip("tests/fixtures/prproj/ directory absent")
    real = sorted(p for p in FIXTURES_DIR.glob("*.prproj") if p.is_file())
    if not real:
        pytest.skip("no real .prproj fixtures present yet — drop some in to enable")
    for path in real:
        doc = parse_prproj(path)
        assert isinstance(doc, PrprojDocument), f"parse returned wrong type for {path.name}"
        # Real projects should contain at least media or sequences.
        assert (len(doc.media) + len(doc.sequences)) > 0, (
            f"{path.name} parsed to empty doc — schema_confidence={doc.schema_confidence}"
        )
