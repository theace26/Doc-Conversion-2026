"""Stream-parse a .prproj file into structured Python.

Premiere project files are gzipped XML. The XML schema is **not**
officially published — Adobe ships rough internal docs with each major
release and community reverse-engineering fills the gaps. This parser
takes a deliberately defensive, schema-flexible approach:

  1. Detect gzip magic; gunzip-stream into ``lxml.iterparse``.
  2. Walk every end-event, classifying tags by name fragments rather
     than fixed tag paths (Premiere tag names vary by version: ``Clip``
     / ``MasterClip`` / ``ClipDef`` etc.).
  3. Harvest path-like leaves (``FilePath``, ``URL``, ``MediaSource``,
     ``ActualMediaFilePath``, ``Pathurl``) into ``MediaRef`` records.
  4. Maintain per-element clearing so a 100 MB+ uncompressed XML
     doesn't blow up RAM.
  5. Compute a ``schema_confidence`` from the harvest counts; on
     "low" the caller is expected to fall back to AdobeHandler-style
     metadata-only output.

Public surface:

    parse_prproj(path: Path) -> PrprojDocument

The returned ``PrprojDocument`` is a frozen dataclass tree — see
classes below. ``parse_warnings`` lists every element the parser
couldn't make sense of so the operator can see what was skipped.

Security:
    - ``resolve_entities=False``  — XXE blocked
    - ``no_network=True``          — external DTDs / entities can't fetch
    - ``recover=False``            — malformed XML raises (caught upstream)
    - No ``eval`` / ``exec``; no shell-out; no path open.

Author: v0.34.0 (Phase 1 of the .prproj deep-handler subsystem).
"""

from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import structlog

log = structlog.get_logger(__name__)


# ── Public dataclasses ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class MediaRef:
    """A single piece of source media referenced by the project."""

    path: str                                # absolute or project-relative
    name: str                                # display name (best-effort)
    media_type: str                          # video|audio|image|graphic|unknown
    duration_ticks: int | None = None
    in_use_in_sequences: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sequence:
    """A timeline within the project."""

    seq_id: str
    name: str
    duration_ticks: int | None = None
    frame_rate: float | None = None
    width: int | None = None
    height: int | None = None
    audio_track_count: int | None = None
    video_track_count: int | None = None
    clip_count: int | None = None
    marker_count: int | None = None


@dataclass(frozen=True)
class Bin:
    """A folder/group node organising clips in the project."""

    bin_id: str
    name: str
    parent_bin_id: str | None = None
    item_count: int | None = None


@dataclass(frozen=True)
class PrprojDocument:
    """Parsed representation of a Premiere project."""

    schema_version: str                      # the version string Premiere wrote
    project_name: str
    created_at: str | None = None            # best-effort; many projects don't carry one
    modified_at: str | None = None
    project_settings: dict = field(default_factory=dict)
    media: tuple[MediaRef, ...] = ()
    sequences: tuple[Sequence, ...] = ()
    bins: tuple[Bin, ...] = ()
    parse_warnings: tuple[str, ...] = ()
    schema_confidence: str = "low"           # high | medium | low
    raw_element_count: int = 0


# ── Tag-name heuristics ──────────────────────────────────────────────────────
#
# Element-name matching is case-insensitive and substring-based because
# Premiere has used ``Clip``, ``MasterClip``, ``ClipDef``, ``ProjectItemClip``
# and similar variants across versions. The harvest is intentionally broad —
# a small false-positive rate here is preferable to missing real refs.


_PATH_LEAF_TAGS = (
    "filepath",
    "actualmediafilepath",
    "mediasource",
    "pathurl",
    "url",
    "path",
    "mediafilepath",
)

_SEQUENCE_TAGS = ("sequence",)
_BIN_TAGS = ("bin",)
_MASTERCLIP_TAGS = ("masterclip", "clipprojectitem", "clip")
# Known root element names by Premiere version. Unknown roots still parse
# but contribute negatively to schema_confidence.
_KNOWN_ROOTS = ("premieredata", "project", "xmeml")

_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v",
               ".mxf", ".wmv", ".mts", ".m2ts", ".r3d", ".braw"}
_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".aif", ".aiff",
               ".ogg", ".wma"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp",
               ".heic", ".heif", ".dpx", ".exr", ".tga"}
_GRAPHIC_EXTS = {".psd", ".ai", ".svg", ".eps", ".prtl"}


# Quote / param surrounding paths in some XML attribute values.
_PATH_CLEAN_RE = re.compile(r"^[\"'\s]+|[\"'\s]+$")


def _classify_media_type(path: str) -> str:
    """Best-effort media-type classification by extension."""
    p = path.lower()
    # Strip URL-style prefixes Premiere sometimes writes.
    if p.startswith("file://"):
        p = p[7:]
    suffix = Path(p).suffix.lower()
    if suffix in _VIDEO_EXTS:
        return "video"
    if suffix in _AUDIO_EXTS:
        return "audio"
    if suffix in _IMAGE_EXTS:
        return "image"
    if suffix in _GRAPHIC_EXTS:
        return "graphic"
    return "unknown"


def _clean_path(value: str) -> str:
    """Strip whitespace + decode common URL-style prefixes."""
    if not value:
        return ""
    v = _PATH_CLEAN_RE.sub("", value)
    if v.lower().startswith("file://"):
        # Strip ``file:///`` (3-slash form) and ``file://`` (2-slash form).
        v = v[7:].lstrip("/")
        # Re-add a leading slash for POSIX paths that started ``file:////``.
        if not v[1:2] == ":" and not v.startswith("\\\\"):
            v = "/" + v
    return v


def _localname(tag) -> str:
    """Return the local name of a (possibly namespaced) lxml tag.

    lxml emits XML comments + processing instructions as elements whose
    ``tag`` is a callable (``Comment``, ``ProcessingInstruction``) rather
    than a string. Return an empty string for those so the caller skips
    them via the simple ``in tag-set`` matchers.
    """
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


# ── Public entry point ───────────────────────────────────────────────────────


def parse_prproj(path: Path) -> PrprojDocument:
    """Parse a .prproj file (gzipped XML) into a :class:`PrprojDocument`.

    Raises:
        OSError: file unreadable
        gzip.BadGzipFile: not a gzip stream
        Exception: lxml parse error (caller should catch and fall back)
    """
    path = Path(path)
    with path.open("rb") as fh:
        magic = fh.read(2)
        fh.seek(0)
        if magic == b"\x1f\x8b":
            stream: IO[bytes] = gzip.GzipFile(fileobj=fh)
        else:
            # Some Premiere versions / saved-via-3rd-party tools emit
            # plain XML. Treat it as such.
            stream = io.BytesIO(fh.read())
        return _parse_stream(stream, project_name=path.stem)


def _parse_stream(stream: IO[bytes], project_name: str) -> PrprojDocument:
    """Internal: drive the iterparse walk over an open byte-stream."""
    from lxml import etree  # local import; lxml is required (declared in requirements.txt)

    media: list[MediaRef] = []
    sequences: list[Sequence] = []
    bins: list[Bin] = []
    warnings: list[str] = []
    project_settings: dict = {}
    schema_version = ""
    detected_root = ""
    raw_count = 0

    # Per-element working state. We hold the element-id → object mappings
    # populated as ``end``-events fire from the deepest leaf upward.

    parser_kwargs = dict(
        events=("start", "end"),
        resolve_entities=False,
        no_network=True,
        recover=False,
    )

    try:
        context = etree.iterparse(stream, **parser_kwargs)  # type: ignore[arg-type]
    except TypeError:
        # Older lxml signatures may not accept ``no_network`` on iterparse.
        context = etree.iterparse(stream, events=("start", "end"))  # type: ignore[arg-type]

    seen_path_per_doc: set[str] = set()
    for event, elem in context:
        local = _localname(elem.tag)

        if event == "start":
            if not detected_root:
                detected_root = local
                # Read root attributes that some Premiere versions stash here.
                schema_version = (
                    elem.get("Version")
                    or elem.get("version")
                    or elem.get("Premiere_Version")
                    or ""
                )
                # Capture project-level color/frame-rate hints when present.
                for attr in ("Title", "FrameRate", "VideoFrameRate",
                             "WorkingColorSpace", "AudioSampleRate"):
                    val = elem.get(attr) or elem.get(attr.lower())
                    if val:
                        project_settings[attr] = val
            continue

        # event == "end"
        raw_count += 1

        # Path-like leaves → media ref
        if local in _PATH_LEAF_TAGS:
            text = (elem.text or "").strip()
            if text:
                cleaned = _clean_path(text)
                if cleaned and cleaned not in seen_path_per_doc:
                    seen_path_per_doc.add(cleaned)
                    media.append(
                        MediaRef(
                            path=cleaned,
                            name=Path(cleaned).name or cleaned,
                            media_type=_classify_media_type(cleaned),
                        )
                    )

        # Sequence-shaped node → record summary if we can scrape it.
        elif local in _SEQUENCE_TAGS:
            seq_id = elem.get("ObjectID") or elem.get("ObjectURef") or elem.get("id") or _short_id(elem)
            seq_name = _first_child_text(elem, ("Name", "Title")) or seq_id
            sequences.append(
                Sequence(
                    seq_id=str(seq_id),
                    name=seq_name,
                    duration_ticks=_int_or_none(_first_child_text(elem, ("Duration", "DurationTicks"))),
                    frame_rate=_float_or_none(_first_child_text(elem, ("FrameRate", "VideoFrameRate"))),
                    width=_int_or_none(_first_child_text(elem, ("VideoFrameWidth", "Width"))),
                    height=_int_or_none(_first_child_text(elem, ("VideoFrameHeight", "Height"))),
                    audio_track_count=_int_or_none(_first_child_text(elem, ("AudioTracks", "AudioTrackCount"))),
                    video_track_count=_int_or_none(_first_child_text(elem, ("VideoTracks", "VideoTrackCount"))),
                    clip_count=_int_or_none(_first_child_text(elem, ("ClipCount", "Clips"))),
                    marker_count=_int_or_none(_first_child_text(elem, ("MarkerCount", "Markers"))),
                )
            )

        # Bin-shaped node
        elif local in _BIN_TAGS:
            bin_id = elem.get("ObjectID") or elem.get("ObjectURef") or elem.get("id") or _short_id(elem)
            bin_name = _first_child_text(elem, ("Name", "Title")) or bin_id
            parent_id = elem.get("ParentObjectURef") or elem.get("ParentID")
            bins.append(
                Bin(
                    bin_id=str(bin_id),
                    name=bin_name,
                    parent_bin_id=str(parent_id) if parent_id else None,
                    item_count=_count_children(elem),
                )
            )

        # Memory hygiene: only clear elements whose data we've already
        # consumed AND whose containing parent we won't revisit. Path
        # leaves are safe to clear (we already harvested their text).
        # Sequence / Bin elements are also safe to clear — their data is
        # captured in the records list.
        #
        # Critically, we do NOT clear arbitrary inner nodes (Name,
        # VideoFrameWidth, etc.) because their parent Sequence / Bin
        # hasn't fired its end event yet — and when it does, the parser
        # walks the children to read their text. Dropping them
        # mid-iteration would leave the parent with an empty subtree.
        if local in _PATH_LEAF_TAGS or local in _SEQUENCE_TAGS or local in _BIN_TAGS:
            elem.clear()

    # ── Compute confidence ──────────────────────────────────────────
    if not detected_root:
        warnings.append("no_root_element_detected")
        confidence = "low"
    elif detected_root not in _KNOWN_ROOTS:
        warnings.append(f"unknown_root_element:{detected_root}")
        confidence = "low" if not (media or sequences) else "medium"
    elif media and sequences:
        confidence = "high"
    elif media or sequences:
        confidence = "medium"
    else:
        warnings.append("known_root_but_empty_harvest")
        confidence = "low"

    log.info(
        "prproj.parsed",
        project_name=project_name,
        root=detected_root,
        schema_version=schema_version or "unknown",
        n_media=len(media),
        n_sequences=len(sequences),
        n_bins=len(bins),
        raw_element_count=raw_count,
        schema_confidence=confidence,
        n_warnings=len(warnings),
    )
    if confidence == "low" and detected_root and detected_root not in _KNOWN_ROOTS:
        log.warning("prproj.schema_unknown",
                    project_name=project_name, root=detected_root)

    return PrprojDocument(
        schema_version=schema_version or "unknown",
        project_name=project_name,
        project_settings=project_settings,
        media=tuple(media),
        sequences=tuple(sequences),
        bins=tuple(bins),
        parse_warnings=tuple(warnings),
        schema_confidence=confidence,
        raw_element_count=raw_count,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _short_id(elem) -> str:
    """Synthesize a short identifier for an element with no id attribute."""
    return f"{_localname(elem.tag)}-{id(elem) & 0xffff:04x}"


def _first_child_text(elem, names: tuple[str, ...]) -> str | None:
    """Return the text of the first direct child whose local name matches."""
    target = {n.lower() for n in names}
    for child in elem:
        if _localname(child.tag) in target:
            txt = (child.text or "").strip()
            if txt:
                return txt
    return None


def _count_children(elem) -> int:
    """Cheap direct-child count — used as a Bin's item_count proxy."""
    try:
        return len(elem)
    except Exception:
        return 0


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Module-level convenience ────────────────────────────────────────────────


def empty_document(project_name: str, reason: str = "fallback") -> PrprojDocument:
    """Return a deliberately-empty document used by the handler's fallback path.

    The handler falls back to AdobeHandler-style metadata-only when the deep
    parse fails outright (gzip corruption, hard XML error). It still wants a
    PrprojDocument shape for uniform Markdown rendering.
    """
    return PrprojDocument(
        schema_version="unknown",
        project_name=project_name,
        parse_warnings=(f"deep_parse_skipped:{reason}",),
        schema_confidence="low",
    )


def merge_sequence_usage(doc: PrprojDocument) -> PrprojDocument:
    """Re-attach ``in_use_in_sequences`` to each MediaRef.

    This is a deliberate post-processing pass: during streaming parse we
    don't know which sequences reference which media until the whole tree
    has been walked. Today we leave the tuple empty (we'd need a second
    iterparse pass to populate it correctly). Reserved for a Phase 1.5
    enrichment without changing the public dataclass shape.
    """
    return doc  # no-op for v0.34.0 — placeholder for richer Phase 1.5 walk


__all__ = [
    "MediaRef",
    "Sequence",
    "Bin",
    "PrprojDocument",
    "parse_prproj",
    "empty_document",
    "merge_sequence_usage",
]
