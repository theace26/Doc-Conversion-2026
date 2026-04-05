"""
Font format handler — OTF/TTF metadata extraction.

Ingest:
  Uses fontTools to extract font metadata: family name, style, version,
  glyph count, Unicode ranges, and copyright. Falls back to basic binary
  header detection if fontTools is unavailable.

Export:
  Not supported — fonts cannot be reconstructed from text.
"""

import time
import unicodedata
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

try:
    from fontTools.ttLib import TTFont

    _HAS_FONTTOOLS = True
except ImportError:
    _HAS_FONTTOOLS = False

# TrueType magic: 00 01 00 00; OpenType magic: OTTO
_TRUETYPE_MAGIC = b"\x00\x01\x00\x00"
_OPENTYPE_MAGIC = b"OTTO"


def _detect_font_type(raw_header: bytes) -> str:
    """Detect font type from the first 4 bytes."""
    if raw_header[:4] == _OPENTYPE_MAGIC:
        return "OpenType (CFF)"
    if raw_header[:4] == _TRUETYPE_MAGIC:
        return "TrueType"
    return "Unknown"


def _get_name_record(font: "TTFont", name_id: int) -> str:
    """Extract a name table record, preferring platformID 3 (Windows)."""
    name_table = font.get("name")
    if not name_table:
        return ""
    record = name_table.getName(name_id, 3, 1, 0x0409)  # Windows, Unicode BMP, English US
    if record is None:
        record = name_table.getName(name_id, 1, 0, 0)  # Mac, Roman, English
    if record is None:
        return ""
    return str(record).strip()


def _get_unicode_ranges(font: "TTFont") -> list[str]:
    """Return a sorted list of Unicode block names covered by the font's cmap."""
    cmap = font.getBestCmap()
    if not cmap:
        return []
    blocks: set[str] = set()
    for codepoint in cmap:
        try:
            char = chr(codepoint)
            block = unicodedata.name(char, "").split()[0] if unicodedata.name(char, "") else None
            if block:
                blocks.add(block)
        except (ValueError, IndexError):
            continue
    # Group by Unicode script/category instead of individual character names
    # Use a simpler approach: collect unique Unicode categories
    categories: set[str] = set()
    for codepoint in cmap:
        try:
            char = chr(codepoint)
            cat = unicodedata.category(char)
            cat_names = {
                "Lu": "Uppercase Letters", "Ll": "Lowercase Letters",
                "Lt": "Titlecase Letters", "Lm": "Modifier Letters",
                "Lo": "Other Letters", "Mn": "Non-spacing Marks",
                "Mc": "Spacing Marks", "Me": "Enclosing Marks",
                "Nd": "Decimal Digits", "Nl": "Letter Numbers",
                "No": "Other Numbers", "Pc": "Connector Punctuation",
                "Pd": "Dash Punctuation", "Ps": "Open Punctuation",
                "Pe": "Close Punctuation", "Pi": "Initial Punctuation",
                "Pf": "Final Punctuation", "Po": "Other Punctuation",
                "Sm": "Math Symbols", "Sc": "Currency Symbols",
                "Sk": "Modifier Symbols", "So": "Other Symbols",
                "Zs": "Space Separators", "Zl": "Line Separators",
                "Zp": "Paragraph Separators", "Cc": "Control Characters",
                "Cf": "Format Characters",
            }
            if cat in cat_names:
                categories.add(cat_names[cat])
        except (ValueError, IndexError):
            continue
    return sorted(categories)


def _get_sample_characters(font: "TTFont", max_chars: int = 80) -> str:
    """Return a sample of printable characters supported by the font."""
    cmap = font.getBestCmap()
    if not cmap:
        return "(no character map found)"
    sample_codepoints = sorted(cmap.keys())
    chars: list[str] = []
    for cp in sample_codepoints:
        if len(chars) >= max_chars:
            break
        try:
            c = chr(cp)
            if c.isprintable() and not c.isspace():
                chars.append(c)
        except (ValueError, OverflowError):
            continue
    return "".join(chars)


def _detect_style(font: "TTFont") -> str:
    """Detect font style from OS/2 table or name records."""
    style_parts: list[str] = []

    # Try OS/2 table flags
    os2 = font.get("OS/2")
    if os2:
        selection = os2.fsSelection
        if selection & 0x0020:  # Bold
            style_parts.append("Bold")
        if selection & 0x0001:  # Italic
            style_parts.append("Italic")
        if not style_parts:
            if selection & 0x0040:  # Regular
                style_parts.append("Regular")

    # Fall back to subfamily name (nameID 2)
    if not style_parts:
        subfamily = _get_name_record(font, 2)
        if subfamily:
            return subfamily

    return " ".join(style_parts) if style_parts else "Regular"


@register_handler
class FontHandler(FormatHandler):
    """OTF/TTF font file handler."""

    EXTENSIONS = ["otf", "ttf"]

    # -- Ingest ----------------------------------------------------------------

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

        if _HAS_FONTTOOLS:
            model = self._ingest_with_fonttools(file_path, model)
        else:
            model = self._ingest_fallback(file_path, model)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
        )
        return model

    def _ingest_with_fonttools(
        self, file_path: Path, model: DocumentModel
    ) -> DocumentModel:
        """Full metadata extraction using fontTools."""
        try:
            font = TTFont(str(file_path), fontNumber=0)
        except Exception as exc:
            model.warnings.append(f"fontTools failed to parse font: {exc}")
            return self._ingest_fallback(file_path, model)

        family = _get_name_record(font, 1) or file_path.stem
        style = _detect_style(font)
        version = _get_name_record(font, 5) or "unknown"
        copyright_info = _get_name_record(font, 0) or "not specified"

        # Glyph count
        glyph_count = len(font.getGlyphOrder())

        # Unicode ranges
        unicode_ranges = _get_unicode_ranges(font)

        # Sample characters
        sample = _get_sample_characters(font)

        font.close()

        # -- Build document elements --

        # H1: filename
        model.add_element(Element(
            type=ElementType.HEADING,
            content=file_path.name,
            level=1,
        ))

        # Summary paragraph
        summary_lines = [
            f"**Font family:** {family}",
            f"**Style:** {style}",
            f"**Version:** {version}",
        ]
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(summary_lines),
        ))

        # Metadata paragraph
        meta_lines = [
            f"**Glyphs:** {glyph_count}",
            f"**Unicode categories:** {', '.join(unicode_ranges) if unicode_ranges else 'unknown'}",
            f"**Copyright:** {copyright_info}",
        ]
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(meta_lines),
        ))

        # Code block: sample characters
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=sample,
            attributes={"language": "text"},
        ))

        return model

    def _ingest_fallback(
        self, file_path: Path, model: DocumentModel
    ) -> DocumentModel:
        """Basic fallback when fontTools is not available."""
        raw = file_path.read_bytes()
        file_size = len(raw)
        font_type = _detect_font_type(raw[:4])

        model.add_element(Element(
            type=ElementType.HEADING,
            content=file_path.name,
            level=1,
        ))

        summary_lines = [
            f"**Font type:** {font_type}",
            f"**File size:** {file_size:,} bytes",
            "*(fontTools not available — detailed metadata extraction skipped)*",
        ]
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(summary_lines),
        ))

        # Show raw header as hex
        header_hex = " ".join(f"{b:02X}" for b in raw[:16])
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=f"Header bytes: {header_hex}",
            attributes={"language": "text"},
        ))

        return model

    # -- Export ----------------------------------------------------------------

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        raise NotImplementedError(
            "Font files (.otf/.ttf) cannot be reconstructed from text."
        )

    # -- Style extraction ------------------------------------------------------

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
