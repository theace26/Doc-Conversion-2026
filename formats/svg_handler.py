"""
SVG format handler — Scalable Vector Graphics extraction.

Ingest:
  Parses SVG XML to extract dimensions, element counts, and text content.

Export:
  Not supported — raises NotImplementedError.
"""

import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import structlog

from formats.base import FormatHandler, register_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)

log = structlog.get_logger(__name__)

_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

# SVG element types we count
_COUNTED_TAGS = {"path", "rect", "circle", "ellipse", "line", "polyline",
                 "polygon", "text", "image", "g", "use", "defs", "clipPath",
                 "linearGradient", "radialGradient", "pattern", "mask"}

_SVG_NS = "http://www.w3.org/2000/svg"


def _local_tag(tag: str) -> str:
    """Strip namespace from an XML tag, e.g. {http://...}rect -> rect."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _detect_encoding(file_path: Path) -> str:
    raw = file_path.read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _collect_text(element: ET.Element) -> list[str]:
    """Recursively collect all text content from <text> elements."""
    texts: list[str] = []
    local = _local_tag(element.tag)
    if local == "text":
        full = "".join(element.itertext()).strip()
        if full:
            texts.append(full)
    else:
        for child in element:
            texts.extend(_collect_text(child))
    return texts


def _count_elements(root: ET.Element) -> Counter:
    """Count SVG elements by local tag name."""
    counts: Counter = Counter()
    for elem in root.iter():
        local = _local_tag(elem.tag)
        if local in _COUNTED_TAGS:
            counts[local] += 1
    return counts


@register_handler
class SvgHandler(FormatHandler):
    """SVG image file handler."""

    EXTENSIONS = ["svg"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        ext = file_path.suffix.lower().lstrip(".")
        log.info("handler_ingest_start", filename=file_path.name, format=ext)

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext,
        )

        encoding = _detect_encoding(file_path)
        text = file_path.read_text(encoding=encoding, errors="replace")

        if not text.strip():
            model.warnings.append("Empty SVG file.")
            return model

        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            model.warnings.append(f"SVG parse error: {exc}")
            model.add_element(Element(
                type=ElementType.HEADING,
                content=file_path.name,
                level=1,
            ))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content=f"**Error:** Could not parse SVG: {exc}",
            ))
            return model

        # Extract root attributes
        width = root.attrib.get("width", "unspecified")
        height = root.attrib.get("height", "unspecified")
        viewbox = root.attrib.get("viewBox", "unspecified")

        # Count elements
        counts = _count_elements(root)
        total_elements = sum(counts.values())

        # Collect text content
        text_content = _collect_text(root)

        # Build model
        model.add_element(Element(
            type=ElementType.HEADING,
            content=file_path.name,
            level=1,
        ))

        # Summary paragraph
        summary_lines = [
            f"**Width:** {width}",
            f"**Height:** {height}",
            f"**viewBox:** {viewbox}",
            f"**Total elements:** {total_elements}",
        ]
        if counts:
            breakdown = ", ".join(
                f"{tag}: {count}" for tag, count in counts.most_common()
            )
            summary_lines.append(f"**Element breakdown:** {breakdown}")

        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(summary_lines),
        ))

        # Text content section
        if text_content:
            model.add_element(Element(
                type=ElementType.HEADING,
                content="Text Content",
                level=2,
            ))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(text_content),
            ))

        # Source code block (first ~100 lines)
        source_lines = text.splitlines()[:100]
        truncated = len(text.splitlines()) > 100
        source_text = "\n".join(source_lines)
        if truncated:
            source_text += "\n<!-- ... truncated ... -->"

        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=source_text,
            attributes={"language": "xml"},
        ))

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
        )
        return model

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        raise NotImplementedError("Export is not supported for SVG files.")

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
