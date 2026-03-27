"""
RTF format handler — Rich Text Format extraction and reconstruction.

Ingest:
  Parses RTF control words to extract paragraphs, headings (by font size),
  bold/italic inline formatting, and basic tables.
  Falls back to striprtf for plain-text extraction on parse errors.

Export:
  Generates RTF 1.x markup from DocumentModel elements.
  Tier 1 only — structural fidelity (paragraphs, headings, tables, lists).
"""

import re
import time
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

# RTF control-word patterns
_CONTROL_WORD = re.compile(r"\\([a-z]+)(-?\d+)?[ ]?")
_CONTROL_SYMBOL = re.compile(r"\\([^a-z\d\n])")
_HEX_ESCAPE = re.compile(r"\\'([0-9a-fA-F]{2})")
_UNICODE_ESCAPE = re.compile(r"\\u(-?\d+)[?]?")

# Font-size threshold: half-points >= this are treated as headings
_HEADING_FS_THRESHOLDS = [
    (48, 1),  # 24pt+ → H1
    (40, 2),  # 20pt+ → H2
    (32, 3),  # 16pt+ → H3
    (28, 4),  # 14pt+ → H4
]
_BODY_FS_DEFAULT = 24  # 12pt in half-points


def _strip_rtf_fallback(raw: str) -> str:
    """Strip RTF to plain text using striprtf library."""
    try:
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(raw)
    except Exception:
        # Last resort: brute-force strip
        text = re.sub(r"\{[^{}]*\}", "", raw)
        text = re.sub(r"\\[a-z]+\d*\s?", "", text)
        text = re.sub(r"[{}]", "", text)
        return text.strip()


def _decode_hex_escapes(text: str, encoding: str = "cp1252") -> str:
    """Replace \\'XX hex escapes with decoded characters."""
    def _repl(m: re.Match) -> str:
        try:
            return bytes.fromhex(m.group(1)).decode(encoding)
        except Exception:
            return ""
    return _HEX_ESCAPE.sub(_repl, text)


def _decode_unicode_escapes(text: str) -> str:
    """Replace \\uN? unicode escapes with characters."""
    def _repl(m: re.Match) -> str:
        code = int(m.group(1))
        if code < 0:
            code += 65536
        try:
            return chr(code)
        except (ValueError, OverflowError):
            return ""
    return _UNICODE_ESCAPE.sub(_repl, text)


class _RtfParser:
    """Lightweight RTF parser that extracts structural elements."""

    def __init__(self, raw: str):
        self.raw = raw
        self.elements: list[Element] = []
        self.font_table: dict[int, str] = {}
        self.encoding = "cp1252"
        self._current_text = ""
        self._bold = False
        self._italic = False
        self._font_size = _BODY_FS_DEFAULT
        self._in_table = False
        self._table_rows: list[list[str]] = []
        self._table_cell_text = ""

    def parse(self) -> list[Element]:
        """Parse RTF and return list of Elements."""
        # Extract font table
        self._parse_font_table()

        # Extract body content (skip header groups)
        body = self._extract_body()
        self._walk(body)
        self._flush_paragraph()
        self._flush_table()
        return self.elements

    def _parse_font_table(self) -> None:
        """Extract font table from RTF header."""
        ft_match = re.search(r"\{\\fonttbl\s*(.*?)\}", self.raw, re.DOTALL)
        if not ft_match:
            return
        ft_content = ft_match.group(1)
        for m in re.finditer(r"\{?\\f(\d+)[^;]*?([A-Za-z ]+);", ft_content):
            self.font_table[int(m.group(1))] = m.group(2).strip()

    def _extract_body(self) -> str:
        """Return the body portion of the RTF, skipping header groups."""
        # Skip {\fonttbl...}, {\colortbl...}, {\stylesheet...}, {\info...}
        body = self.raw
        # Remove known header groups
        for group_name in ("fonttbl", "colortbl", "stylesheet", "info", "\\*\\generator"):
            pattern = re.compile(r"\{[^{}]*?" + re.escape(group_name) + r"[^{}]*?(\{[^{}]*\}[^{}]*?)*\}", re.DOTALL)
            body = pattern.sub("", body)
        # Remove the outermost braces and \rtf declaration
        body = re.sub(r"^\s*\{\\rtf\d?\s*", "", body)
        body = re.sub(r"\}\s*$", "", body)
        return body

    def _walk(self, text: str) -> None:
        """Walk through RTF content, extracting elements."""
        i = 0
        while i < len(text):
            ch = text[i]

            if ch == "{":
                # Find matching close brace
                depth = 1
                j = i + 1
                while j < len(text) and depth > 0:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    elif text[j] == "\\":
                        j += 1  # skip escaped char
                    j += 1
                group = text[i + 1 : j - 1]
                # Skip special groups (pictures, etc.)
                if group.startswith("\\pict") or group.startswith("\\*\\shp"):
                    pass  # skip images for now
                else:
                    self._walk(group)
                i = j
                continue

            if ch == "}":
                i += 1
                continue

            if ch == "\\":
                # Control word or symbol
                cw_match = _CONTROL_WORD.match(text, i)
                if cw_match:
                    word = cw_match.group(1)
                    param = int(cw_match.group(2)) if cw_match.group(2) else None
                    self._handle_control(word, param)
                    i = cw_match.end()
                    continue

                cs_match = _CONTROL_SYMBOL.match(text, i)
                if cs_match:
                    sym = cs_match.group(1)
                    if sym == "~":
                        self._current_text += "\u00a0"  # non-breaking space
                    elif sym == "-":
                        pass  # optional hyphen
                    elif sym == "\n" or sym == "\r":
                        pass  # line break in source
                    i = cs_match.end()
                    continue

                # Unicode escape
                uni_match = _UNICODE_ESCAPE.match(text, i)
                if uni_match:
                    code = int(uni_match.group(1))
                    if code < 0:
                        code += 65536
                    try:
                        self._current_text += chr(code)
                    except (ValueError, OverflowError):
                        pass
                    i = uni_match.end()
                    continue

                # Hex escape
                hex_match = _HEX_ESCAPE.match(text, i)
                if hex_match:
                    try:
                        self._current_text += bytes.fromhex(hex_match.group(1)).decode(self.encoding)
                    except Exception:
                        pass
                    i = hex_match.end()
                    continue

                i += 1
                continue

            if ch in ("\r", "\n"):
                i += 1
                continue

            # Regular character
            self._current_text += ch
            i += 1

    def _handle_control(self, word: str, param: int | None) -> None:
        """Handle a single RTF control word."""
        if word == "par" or word == "line":
            self._flush_paragraph()
        elif word == "tab":
            self._current_text += "\t"
        elif word == "b":
            self._bold = param != 0 if param is not None else True
        elif word == "i":
            self._italic = param != 0 if param is not None else True
        elif word == "fs":
            self._font_size = param or _BODY_FS_DEFAULT
        elif word == "pard":
            # Paragraph default — reset inline state
            self._bold = False
            self._italic = False
            self._font_size = _BODY_FS_DEFAULT
        elif word == "cell":
            # End of table cell
            self._table_cell_text = self._current_text.strip()
            self._current_text = ""
        elif word == "row":
            # End of table row
            if self._table_cell_text or self._current_text.strip():
                # Collect last cell if not already flushed by \cell
                if self._current_text.strip():
                    self._table_cell_text = self._current_text.strip()
                    self._current_text = ""
            self._in_table = True
        elif word == "trowd":
            # Table row definition — start collecting
            self._in_table = True
        elif word == "intbl":
            self._in_table = True
        elif word == "sect":
            self._flush_paragraph()
        elif word == "page":
            self._flush_paragraph()
            self.elements.append(Element(type=ElementType.PAGE_BREAK, content=""))

    def _flush_paragraph(self) -> None:
        """Emit the accumulated text as an Element."""
        text = self._current_text.strip()
        self._current_text = ""

        if not text:
            return

        if self._in_table:
            # Accumulate as table data — handled by row/cell controls
            return

        # Determine element type based on font size
        elem_type = ElementType.PARAGRAPH
        level = None

        for fs_threshold, heading_level in _HEADING_FS_THRESHOLDS:
            if self._font_size >= fs_threshold:
                elem_type = ElementType.HEADING
                level = heading_level
                break

        # Apply inline formatting to text
        if self._bold and self._italic:
            text = f"***{text}***"
        elif self._bold:
            text = f"**{text}**"
        elif self._italic:
            text = f"*{text}*"

        self.elements.append(Element(
            type=elem_type,
            content=text,
            level=level,
        ))

    def _flush_table(self) -> None:
        """Emit any accumulated table rows."""
        if self._table_rows:
            self.elements.append(Element(
                type=ElementType.TABLE,
                content=self._table_rows,
            ))
            self._table_rows = []
            self._in_table = False


@register_handler
class RtfHandler(FormatHandler):
    """RTF format handler — Rich Text Format."""

    EXTENSIONS = ["rtf"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="rtf")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="rtf",
        )

        raw = self._read_rtf(file_path)
        if not raw:
            model.warnings.append("Empty RTF file — no data extracted.")
            return model

        # Try structured parse first
        try:
            parser = _RtfParser(raw)
            elements = parser.parse()
            if elements:
                for elem in elements:
                    model.add_element(elem)
                model.style_data["rtf_font_table"] = parser.font_table
                model.style_data["rtf_encoding"] = parser.encoding
            else:
                # Structured parse returned nothing — fall back
                self._fallback_ingest(raw, model)
        except Exception as exc:
            log.debug("rtf.structured_parse_failed", error=str(exc))
            self._fallback_ingest(raw, model)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
        )
        return model

    def _read_rtf(self, file_path: Path) -> str:
        """Read RTF file with encoding detection."""
        raw_bytes = file_path.read_bytes()
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw_bytes.decode("latin-1")

    def _fallback_ingest(self, raw: str, model: DocumentModel) -> None:
        """Fall back to striprtf plain-text extraction and split into paragraphs."""
        text = _strip_rtf_fallback(raw)
        if not text:
            model.warnings.append("RTF parse fallback produced no content.")
            return

        model.warnings.append("Used plain-text fallback — formatting may be lost.")
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content=para,
                ))

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="rtf", tier=1)

        lines: list[str] = []
        lines.append(r"{\rtf1\ansi\deff0")
        lines.append(r"{\fonttbl{\f0\fswiss Calibri;}{\f1\fmodern Courier New;}}")
        lines.append(r"{\colortbl;\red0\green0\blue0;}")
        lines.append("")

        for elem in model.elements:
            if elem.type == ElementType.HEADING:
                level = elem.level or 1
                # Map heading level to font size (half-points)
                fs_map = {1: 48, 2: 40, 3: 32, 4: 28, 5: 26, 6: 24}
                fs = fs_map.get(level, 24)
                text = self._escape_rtf(self._strip_md_formatting(elem.content))
                lines.append(rf"\pard\sa200\b\fs{fs} {text}\b0\fs24\par")

            elif elem.type == ElementType.PARAGRAPH:
                text = self._escape_rtf(self._strip_md_formatting(elem.content))
                lines.append(rf"\pard\sa120\fs24 {text}\par")

            elif elem.type == ElementType.TABLE:
                rows = elem.content
                if isinstance(rows, list) and rows:
                    for row in rows:
                        if not isinstance(row, list):
                            continue
                        # Simple table: one cell per column
                        cell_width = 9000 // max(len(row), 1)
                        lines.append(r"\trowd")
                        for ci in range(len(row)):
                            lines.append(rf"\cellx{cell_width * (ci + 1)}")
                        for cell in row:
                            text = self._escape_rtf(str(cell))
                            lines.append(rf"\pard\intbl\fs24 {text}\cell")
                        lines.append(r"\row")

            elif elem.type == ElementType.CODE_BLOCK:
                text = self._escape_rtf(elem.content)
                lines.append(rf"\pard\sa120\f1\fs20 {text}\f0\fs24\par")

            elif elem.type == ElementType.BLOCKQUOTE:
                text = self._escape_rtf(self._strip_md_formatting(elem.content))
                lines.append(rf"\pard\li720\sa120\i\fs24 {text}\i0\par")

            elif elem.type == ElementType.LIST_ITEM:
                text = self._escape_rtf(self._strip_md_formatting(elem.content))
                bullet = r"\'95"  # bullet character
                lines.append(rf"\pard\li360\sa60\fs24 {bullet} {text}\par")

            elif elem.type == ElementType.HORIZONTAL_RULE:
                lines.append(r"\pard\brdrb\brdrs\brdrw10\sa200 \par")

            elif elem.type == ElementType.PAGE_BREAK:
                lines.append(r"\page")

            elif elem.type == ElementType.FOOTNOTE:
                fn_id = elem.attributes.get("id", "")
                text = self._escape_rtf(elem.content)
                lines.append(rf"\pard\sa60\fs20 [{fn_id}] {text}\fs24\par")

        lines.append("}")

        output_path.write_text("\n".join(lines), encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_export_complete",
            filename=output_path.name,
            output_path=str(output_path),
            duration_ms=duration_ms,
        )

    @staticmethod
    def _escape_rtf(text: str) -> str:
        """Escape special RTF characters."""
        text = text.replace("\\", "\\\\")
        text = text.replace("{", "\\{")
        text = text.replace("}", "\\}")
        # Escape non-ASCII as unicode
        out: list[str] = []
        for ch in text:
            if ord(ch) > 127:
                out.append(f"\\u{ord(ch)}?")
            else:
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _strip_md_formatting(text: str) -> str:
        """Remove Markdown bold/italic markers from text."""
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """Extract font table and encoding info from RTF."""
        raw = self._read_rtf(file_path)
        styles: dict[str, Any] = {
            "document_level": {
                "extension": ".rtf",
                "encoding": "cp1252",
            }
        }

        if not raw:
            return styles

        # Extract font table
        parser = _RtfParser(raw)
        parser._parse_font_table()
        if parser.font_table:
            styles["document_level"]["font_table"] = {
                str(k): v for k, v in parser.font_table.items()
            }

        # Detect default font size
        fs_match = re.search(r"\\fs(\d+)", raw)
        if fs_match:
            styles["document_level"]["default_font_size_halfpts"] = int(fs_match.group(1))

        return styles
