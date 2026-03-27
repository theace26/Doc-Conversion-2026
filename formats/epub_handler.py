"""
EPUB format handler — ebook document extraction and reconstruction.

Ingest:
  Uses ebooklib to read EPUB spine items. Parses HTML content of each
  chapter with BeautifulSoup. Extracts headings, paragraphs, tables,
  images, and captures embedded font references.

Export:
  Generates EPUB3 with semantic HTML chapters from DocumentModel.
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

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


@register_handler
class EpubHandler(FormatHandler):
    """EPUB ebook handler."""

    EXTENSIONS = ["epub"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="epub")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="epub",
        )

        book = epub.read_epub(str(file_path))

        # Extract metadata
        title = book.get_metadata("DC", "title")
        if title:
            model.metadata.title = title[0][0] if title[0] else ""
        creator = book.get_metadata("DC", "creator")
        if creator:
            model.metadata.author = creator[0][0] if creator[0] else ""

        # Extract font references from CSS
        fonts = set()
        for item in book.get_items_of_type(ebooklib.ITEM_STYLE):
            css = item.get_content().decode("utf-8", errors="replace")
            for m in re.finditer(r"font-family:\s*([^;}{]+)", css, re.IGNORECASE):
                for f in m.group(1).split(","):
                    f = f.strip().strip("'\"")
                    if f and f.lower() not in ("inherit", "initial", "serif", "sans-serif", "monospace"):
                        fonts.add(f)
        if fonts:
            model.style_data["epub_fonts"] = sorted(fonts)

        # Extract embedded font file names
        font_files = []
        for item in book.get_items_of_type(ebooklib.ITEM_FONT):
            font_files.append(item.get_name())
        if font_files:
            model.style_data["epub_font_files"] = font_files

        # Process spine items (chapters in reading order)
        chapter_count = 0
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            html_content = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(html_content, "html.parser")
            body = soup.find("body") or soup

            chapter_count += 1
            had_content = False

            for tag in body.descendants:
                if not hasattr(tag, "name") or tag.name is None:
                    continue

                name = tag.name.lower()

                if name in _HEADING_TAGS:
                    text = tag.get_text(strip=True)
                    if text:
                        model.add_element(Element(
                            type=ElementType.HEADING,
                            content=text,
                            level=_HEADING_TAGS[name],
                        ))
                        had_content = True

                elif name == "p":
                    # Skip if parent is already processed (e.g., blockquote > p)
                    text = tag.get_text(strip=True)
                    if text and tag.parent and tag.parent.name not in ("blockquote",):
                        model.add_element(Element(
                            type=ElementType.PARAGRAPH,
                            content=text,
                        ))
                        had_content = True

                elif name == "blockquote":
                    text = tag.get_text(strip=True)
                    if text:
                        model.add_element(Element(
                            type=ElementType.BLOCKQUOTE,
                            content=text,
                        ))
                        had_content = True

            if had_content and chapter_count > 1:
                # Insert page break between chapters
                model.elements.insert(-1 if model.elements else 0,
                    Element(type=ElementType.PAGE_BREAK, content=""))

        model.metadata.page_count = chapter_count or 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        from ebooklib import epub

        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="epub", tier=1)

        book = epub.EpubBook()
        book.set_identifier("markflow-export")
        book.set_title(model.metadata.title or model.metadata.source_file)
        book.set_language("en")
        if model.metadata.author:
            book.add_author(model.metadata.author)

        # Build chapters from page breaks
        chapters: list[list[str]] = [[]]
        for elem in model.elements:
            if elem.type == ElementType.PAGE_BREAK:
                chapters.append([])
                continue

            if elem.type == ElementType.HEADING:
                level = elem.level or 1
                text = self._escape(self._strip_md(elem.content))
                chapters[-1].append(f"<h{level}>{text}</h{level}>")
            elif elem.type == ElementType.PARAGRAPH:
                text = self._escape(self._strip_md(elem.content))
                chapters[-1].append(f"<p>{text}</p>")
            elif elem.type == ElementType.BLOCKQUOTE:
                text = self._escape(self._strip_md(elem.content))
                chapters[-1].append(f"<blockquote><p>{text}</p></blockquote>")
            elif elem.type == ElementType.CODE_BLOCK:
                chapters[-1].append(f"<pre><code>{self._escape(elem.content)}</code></pre>")
            elif elem.type == ElementType.LIST_ITEM:
                text = self._escape(self._strip_md(elem.content))
                chapters[-1].append(f"<ul><li>{text}</li></ul>")

        epub_chapters = []
        spine = ["nav"]
        toc = []

        for i, html_parts in enumerate(chapters):
            if not html_parts:
                continue
            ch = epub.EpubHtml(title=f"Chapter {i + 1}", file_name=f"chap_{i + 1}.xhtml", lang="en")
            ch.content = "<body>" + "\n".join(html_parts) + "</body>"
            book.add_item(ch)
            epub_chapters.append(ch)
            spine.append(ch)
            toc.append(epub.Link(f"chap_{i + 1}.xhtml", f"Chapter {i + 1}", f"chap_{i + 1}"))

        book.toc = toc
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = spine

        epub.write_epub(str(output_path), book, {})

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _strip_md(text: str) -> str:
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(file_path))
        fonts = set()

        for item in book.get_items_of_type(ebooklib.ITEM_STYLE):
            css = item.get_content().decode("utf-8", errors="replace")
            for m in re.finditer(r"font-family:\s*([^;}{]+)", css, re.IGNORECASE):
                for f in m.group(1).split(","):
                    f = f.strip().strip("'\"")
                    if f and f.lower() not in ("inherit", "initial", "serif", "sans-serif", "monospace"):
                        fonts.add(f)

        font_files = []
        for item in book.get_items_of_type(ebooklib.ITEM_FONT):
            font_files.append(item.get_name())

        return {
            "document_level": {
                "extension": ".epub",
                "fonts": sorted(fonts),
                "font_files": font_files,
            }
        }
