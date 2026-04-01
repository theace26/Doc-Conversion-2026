"""
OpenDocument Text handler — ODT files (LibreOffice, Google Docs export).

Ingest:
  Uses odfpy to parse ODT XML structure. Extracts headings, paragraphs,
  tables, lists, and images. Captures font declarations for reconstruction.

Export:
  Generates ODT via odfpy with font reconstruction from sidecar data.
"""

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


@register_handler
class OdtHandler(FormatHandler):
    """OpenDocument Text (.odt) handler."""

    EXTENSIONS = ["odt"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        from odf.opendocument import load as odf_load
        from odf import text as odf_text, table as odf_table
        from odf.namespaces import TEXTNS, TABLENS, FONS

        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="odt")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="odt",
        )

        doc = odf_load(str(file_path))

        # Extract document metadata
        meta = doc.meta
        if meta:
            for child in meta.childNodes:
                tag = child.qname[1] if hasattr(child, "qname") else ""
                text_content = self._get_text(child)
                if "title" in tag.lower() and text_content:
                    model.metadata.title = text_content
                elif "creator" in tag.lower() and text_content:
                    model.metadata.author = text_content
                elif "subject" in tag.lower() and text_content:
                    model.metadata.subject = text_content

        # Extract font declarations
        fonts = self._extract_fonts(doc)
        if fonts:
            model.style_data["odt_fonts"] = fonts

        # Walk document body
        body = doc.body
        office_text = body.getElementsByType(odf_text.P) + body.getElementsByType(odf_text.H)

        # Process in document order by walking body children
        for child in body.childNodes:
            if not hasattr(child, "qname"):
                continue

            tag_name = child.qname[1] if child.qname else ""

            if tag_name == "text":
                # Office text container
                for elem in child.childNodes:
                    self._process_odf_element(elem, model)
            else:
                self._process_odf_element(child, model)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _process_odf_element(self, elem, model: DocumentModel) -> None:
        if not hasattr(elem, "qname"):
            return

        tag = elem.qname[1] if elem.qname else ""

        if tag == "h":
            # Heading
            text = self._get_text(elem).strip()
            level = 1
            try:
                outline = elem.getAttribute("outlinelevel")
                if outline:
                    level = int(outline)
            except (ValueError, TypeError):
                pass
            if text:
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=text,
                    level=min(level, 6),
                ))

        elif tag == "p":
            text = self._get_text(elem).strip()
            if text:
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content=text,
                ))

        elif tag == "table":
            rows = self._extract_odf_table(elem)
            if rows:
                model.add_element(Element(
                    type=ElementType.TABLE,
                    content=rows,
                ))

        elif tag == "list":
            for item in elem.childNodes:
                if hasattr(item, "qname") and item.qname[1] == "list-item":
                    text = self._get_text(item).strip()
                    if text:
                        model.add_element(Element(
                            type=ElementType.LIST_ITEM,
                            content=text,
                        ))

    def _extract_odf_table(self, table_elem) -> list[list[str]]:
        rows: list[list[str]] = []
        for child in table_elem.childNodes:
            if not hasattr(child, "qname"):
                continue
            if child.qname[1] == "table-row":
                cells: list[str] = []
                for cell in child.childNodes:
                    if hasattr(cell, "qname") and cell.qname[1] == "table-cell":
                        cells.append(self._get_text(cell).strip())
                if cells:
                    rows.append(cells)
        return rows

    def _extract_fonts(self, doc) -> list[str]:
        """Extract font declarations from the document."""
        from formats.odf_utils import extract_odf_fonts
        return extract_odf_fonts(doc, include_fontfamily=True)

    @staticmethod
    def _get_text(node) -> str:
        """Recursively extract text from an ODF node."""
        from formats.odf_utils import get_odf_text
        return get_odf_text(node)

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        from odf.opendocument import OpenDocumentText
        from odf import text as odf_text
        from odf.style import Style, TextProperties, ParagraphProperties
        from odf.text import P, H

        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="odt", tier=1)

        doc = OpenDocumentText()

        # Create heading styles
        for i in range(1, 7):
            hs = Style(name=f"Heading{i}", family="paragraph")
            hs.addElement(TextProperties(
                fontsize=f"{24 - (i - 1) * 2}pt",
                fontweight="bold",
            ))
            doc.styles.addElement(hs)

        # Reconstruct fonts from sidecar
        if sidecar:
            font_name = sidecar.get("document_level", {}).get("default_font", "")
            if font_name:
                body_style = Style(name="BodyText", family="paragraph")
                body_style.addElement(TextProperties(fontname=font_name))
                doc.styles.addElement(body_style)

        for elem in model.elements:
            if elem.type == ElementType.HEADING:
                level = elem.level or 1
                h = H(outlinelevel=str(level), stylename=f"Heading{level}")
                h.addText(self._strip_md(elem.content))
                doc.text.addElement(h)

            elif elem.type == ElementType.PARAGRAPH:
                p = P()
                p.addText(self._strip_md(elem.content))
                doc.text.addElement(p)

            elif elem.type == ElementType.CODE_BLOCK:
                p = P()
                p.addText(elem.content)
                doc.text.addElement(p)

            elif elem.type == ElementType.BLOCKQUOTE:
                p = P()
                p.addText(self._strip_md(elem.content))
                doc.text.addElement(p)

            elif elem.type == ElementType.LIST_ITEM:
                p = P()
                p.addText("- " + self._strip_md(elem.content))
                doc.text.addElement(p)

            elif elem.type == ElementType.TABLE:
                # ODT tables via odfpy are complex — fall back to tab-separated text
                rows = elem.content
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, list):
                            p = P()
                            p.addText("\t".join(str(c) for c in row))
                            doc.text.addElement(p)

        doc.save(str(output_path))

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    @staticmethod
    def _strip_md(text: str) -> str:
        import re
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        from odf.opendocument import load as odf_load

        doc = odf_load(str(file_path))
        fonts = self._extract_fonts(doc)

        styles_info: dict[str, Any] = {
            "document_level": {
                "extension": ".odt",
                "fonts": fonts,
                "default_font": fonts[0] if fonts else "",
            }
        }
        return styles_info
