"""
OpenDocument Presentation handler — ODP files.

Ingest:
  Uses odfpy to parse ODP slides. Each slide's text frames become
  headings and paragraphs. Captures font declarations.

Export:
  Generates ODP via odfpy from DocumentModel elements.
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
class OdpHandler(FormatHandler):
    """OpenDocument Presentation (.odp) handler."""

    EXTENSIONS = ["odp"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        from odf.opendocument import load as odf_load

        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="odp")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="odp",
        )

        doc = odf_load(str(file_path))
        slides = self._extract_slides(doc)

        for slide_num, (title, paragraphs) in enumerate(slides, 1):
            if title:
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=title,
                    level=2,
                    attributes={"slide_number": slide_num},
                ))
            for para in paragraphs:
                if para.strip():
                    model.add_element(Element(
                        type=ElementType.PARAGRAPH,
                        content=para,
                        attributes={"slide_number": slide_num},
                    ))

            if slide_num < len(slides):
                model.add_element(Element(type=ElementType.PAGE_BREAK, content=""))

        fonts = self._extract_fonts(doc)
        if fonts:
            model.style_data["odp_fonts"] = fonts

        model.metadata.page_count = len(slides) or 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _extract_slides(self, doc) -> list[tuple[str, list[str]]]:
        """Return list of (title, [paragraphs]) per slide."""
        slides: list[tuple[str, list[str]]] = []
        body = doc.body
        for child in body.childNodes:
            if not hasattr(child, "qname"):
                continue
            if child.qname[1] == "presentation":
                for page in child.childNodes:
                    if hasattr(page, "qname") and page.qname[1] == "page":
                        title, paras = self._extract_page(page)
                        slides.append((title, paras))
        return slides

    def _extract_page(self, page) -> tuple[str, list[str]]:
        title = ""
        paragraphs: list[str] = []
        first_frame = True

        for frame in page.childNodes:
            if not hasattr(frame, "qname"):
                continue
            if frame.qname[1] == "frame":
                texts = self._extract_frame_texts(frame)
                if first_frame and texts:
                    title = texts[0]
                    paragraphs.extend(texts[1:])
                    first_frame = False
                else:
                    paragraphs.extend(texts)

        return title, paragraphs

    def _extract_frame_texts(self, frame) -> list[str]:
        texts: list[str] = []
        for child in frame.childNodes:
            if hasattr(child, "qname") and child.qname[1] == "text-box":
                for elem in child.childNodes:
                    text = self._get_text(elem).strip()
                    if text:
                        texts.append(text)
        return texts

    def _extract_fonts(self, doc) -> list[str]:
        fonts = set()
        try:
            font_decls = doc.fontfacedecls
            if font_decls:
                for child in font_decls.childNodes:
                    if hasattr(child, "getAttribute"):
                        name = child.getAttribute("name")
                        if name:
                            fonts.add(name)
        except Exception:
            pass
        return sorted(fonts)

    @staticmethod
    def _get_text(node) -> str:
        if hasattr(node, "data"):
            return node.data or ""
        parts: list[str] = []
        if hasattr(node, "childNodes"):
            for child in node.childNodes:
                parts.append(OdpHandler._get_text(child))
        return "".join(parts)

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        from odf.opendocument import OpenDocumentPresentation
        from odf.draw import Frame, Page, TextBox
        from odf.text import P

        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="odp", tier=1)

        doc = OpenDocumentPresentation()

        current_page = Page(masterpagename="Default")
        current_texts: list[str] = []

        def flush_page():
            nonlocal current_page, current_texts
            if current_texts:
                frame = Frame(width="25cm", height="18cm", x="1cm", y="1cm")
                tb = TextBox()
                for text in current_texts:
                    p = P()
                    p.addText(text)
                    tb.addElement(p)
                frame.addElement(tb)
                current_page.addElement(frame)
            doc.presentation.addElement(current_page)
            current_page = Page(masterpagename="Default")
            current_texts = []

        for elem in model.elements:
            if elem.type == ElementType.PAGE_BREAK:
                flush_page()
            elif elem.type in (ElementType.HEADING, ElementType.PARAGRAPH):
                current_texts.append(self._strip_md(elem.content))
            elif elem.type == ElementType.LIST_ITEM:
                current_texts.append("- " + self._strip_md(elem.content))

        flush_page()

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

        return {
            "document_level": {
                "extension": ".odp",
                "fonts": fonts,
                "default_font": fonts[0] if fonts else "",
            }
        }
