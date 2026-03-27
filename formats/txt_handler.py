"""
Plain text format handler — TXT, LOG, TEXT files.

Ingest:
  Reads with encoding detection. Splits into paragraphs on double newlines.
  Detects simple heading patterns (ALL CAPS lines, underlined lines).

Export:
  Writes DocumentModel as plain text with blank-line paragraph separation.
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

_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

# Heuristic: short ALL-CAPS line followed by content → heading
_ALL_CAPS_LINE = re.compile(r"^[A-Z][A-Z0-9 &/,.\-:]{2,80}$")
# Underlined heading: line followed by ===== or -----
_UNDERLINE_H1 = re.compile(r"^(.+)\n={3,}\s*$", re.MULTILINE)
_UNDERLINE_H2 = re.compile(r"^(.+)\n-{3,}\s*$", re.MULTILINE)


@register_handler
class TxtHandler(FormatHandler):
    """Plain text handler for .txt, .log, .text files."""

    EXTENSIONS = ["txt", "log", "text"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="txt")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=file_path.suffix.lower().lstrip("."),
        )

        encoding = self._detect_encoding(file_path)
        text = file_path.read_text(encoding=encoding, errors="replace")

        if not text.strip():
            model.warnings.append("Empty text file.")
            return model

        model.style_data["txt_encoding"] = encoding

        # Detect underlined headings first
        text = _UNDERLINE_H1.sub(lambda m: f"\x01H1\x02{m.group(1)}\x03", text)
        text = _UNDERLINE_H2.sub(lambda m: f"\x01H2\x02{m.group(1)}\x03", text)

        # Split into blocks on double newlines
        blocks = re.split(r"\n{2,}", text)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Check for inserted heading markers
            h_match = re.match(r"\x01(H[12])\x02(.+)\x03", block)
            if h_match:
                level = 1 if h_match.group(1) == "H1" else 2
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=h_match.group(2).strip(),
                    level=level,
                ))
                continue

            # Heuristic: short ALL CAPS line → heading
            if _ALL_CAPS_LINE.match(block) and len(block) < 80:
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=block,
                    level=2,
                ))
                continue

            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content=block,
            ))

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _detect_encoding(self, file_path: Path) -> str:
        raw = file_path.read_bytes()
        for enc in _ENCODINGS:
            try:
                raw.decode(enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue
        return "latin-1"

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="txt", tier=1)

        encoding = "utf-8"
        if sidecar:
            encoding = sidecar.get("document_level", {}).get("encoding", encoding)

        parts: list[str] = []
        for elem in model.elements:
            if elem.type == ElementType.HEADING:
                text = self._strip_md(elem.content)
                parts.append(text.upper() if (elem.level or 1) <= 2 else text)
            elif elem.type == ElementType.TABLE:
                rows = elem.content
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, list):
                            parts.append("\t".join(str(c) for c in row))
            elif elem.type == ElementType.HORIZONTAL_RULE:
                parts.append("-" * 40)
            elif elem.type == ElementType.PAGE_BREAK:
                parts.append("\f")
            else:
                parts.append(self._strip_md(elem.content))

        output_path.write_text("\n\n".join(parts) + "\n", encoding=encoding)

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    @staticmethod
    def _strip_md(text: str) -> str:
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        encoding = self._detect_encoding(file_path)
        return {
            "document_level": {
                "extension": file_path.suffix.lower(),
                "encoding": encoding,
                "font_family": "monospace",
                "font_name": "Courier New",
            }
        }
