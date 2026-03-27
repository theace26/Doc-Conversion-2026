"""
HTML format handler — HTML/HTM document extraction and reconstruction.

Ingest:
  Parses HTML with BeautifulSoup. Extracts headings, paragraphs, tables,
  images, code blocks, blockquotes, and lists into DocumentModel elements.
  Captures font information from inline styles and stylesheets.

Export:
  Generates semantic HTML5 from DocumentModel with optional font reconstruction
  from sidecar style data.
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
_FONT_STYLE_RE = re.compile(r"font-family:\s*([^;\"']+)", re.IGNORECASE)
_FONT_SIZE_RE = re.compile(r"font-size:\s*([^;\"']+)", re.IGNORECASE)


@register_handler
class HtmlHandler(FormatHandler):
    """HTML/HTM format handler."""

    EXTENSIONS = ["html", "htm"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        from bs4 import BeautifulSoup

        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="html")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="html",
        )

        raw = self._read_html(file_path)
        if not raw.strip():
            model.warnings.append("Empty HTML file.")
            return model

        soup = BeautifulSoup(raw, "html.parser")

        # Extract title
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            model.metadata.title = title_tag.string.strip()

        # Extract font info from stylesheets
        fonts = self._extract_fonts_from_styles(soup)
        if fonts:
            model.style_data["html_fonts"] = fonts

        # Process body (or whole document if no body tag)
        body = soup.find("body") or soup

        for tag in body.children:
            self._process_tag(tag, model)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _read_html(self, file_path: Path) -> str:
        raw_bytes = file_path.read_bytes()
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw_bytes.decode("latin-1")

    def _extract_fonts_from_styles(self, soup) -> list[str]:
        """Extract font-family declarations from style tags and inline styles."""
        fonts = set()
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                for m in _FONT_STYLE_RE.finditer(style_tag.string):
                    for f in m.group(1).split(","):
                        f = f.strip().strip("'\"")
                        if f and f.lower() not in ("inherit", "initial", "unset"):
                            fonts.add(f)
        for tag in soup.find_all(style=True):
            style = tag.get("style", "")
            for m in _FONT_STYLE_RE.finditer(style):
                for f in m.group(1).split(","):
                    f = f.strip().strip("'\"")
                    if f and f.lower() not in ("inherit", "initial", "unset"):
                        fonts.add(f)
        return sorted(fonts)

    def _process_tag(self, tag, model: DocumentModel) -> None:
        from bs4 import NavigableString, Tag

        if isinstance(tag, NavigableString):
            text = str(tag).strip()
            if text:
                model.add_element(Element(type=ElementType.PARAGRAPH, content=text))
            return

        if not isinstance(tag, Tag):
            return

        name = tag.name.lower()

        if name in _HEADING_TAGS:
            text = tag.get_text(strip=True)
            if text:
                attrs = {}
                font = self._get_inline_font(tag)
                if font:
                    attrs["font_family"] = font
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=text,
                    level=_HEADING_TAGS[name],
                    attributes=attrs,
                ))

        elif name == "p":
            text = tag.get_text(strip=True)
            if text:
                attrs = {}
                font = self._get_inline_font(tag)
                if font:
                    attrs["font_family"] = font
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content=text,
                    attributes=attrs,
                ))

        elif name == "table":
            rows = self._extract_table(tag)
            if rows:
                model.add_element(Element(type=ElementType.TABLE, content=rows))

        elif name in ("pre", "code"):
            text = tag.get_text()
            if text.strip():
                lang = tag.get("class", [""])[0] if tag.get("class") else ""
                lang = lang.replace("language-", "") if lang.startswith("language-") else ""
                model.add_element(Element(
                    type=ElementType.CODE_BLOCK,
                    content=text,
                    attributes={"language": lang} if lang else {},
                ))

        elif name == "blockquote":
            text = tag.get_text(strip=True)
            if text:
                model.add_element(Element(type=ElementType.BLOCKQUOTE, content=text))

        elif name in ("ul", "ol"):
            for li in tag.find_all("li", recursive=False):
                text = li.get_text(strip=True)
                if text:
                    model.add_element(Element(
                        type=ElementType.LIST_ITEM,
                        content=text,
                        attributes={"ordered": name == "ol"},
                    ))

        elif name == "hr":
            model.add_element(Element(type=ElementType.HORIZONTAL_RULE, content=""))

        elif name == "img":
            alt = tag.get("alt", "")
            src = tag.get("src", "")
            model.add_element(Element(
                type=ElementType.IMAGE,
                content=alt or src,
                attributes={"src": src, "alt": alt},
            ))

        elif name in ("div", "section", "article", "main", "header", "footer", "nav", "aside", "span"):
            for child in tag.children:
                self._process_tag(child, model)

    def _extract_table(self, table_tag) -> list[list[str]]:
        rows: list[list[str]] = []
        for tr in table_tag.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                cells.append(td.get_text(strip=True))
            if cells:
                rows.append(cells)
        return rows

    @staticmethod
    def _get_inline_font(tag) -> str | None:
        style = tag.get("style", "")
        m = _FONT_STYLE_RE.search(style)
        if m:
            return m.group(1).split(",")[0].strip().strip("'\"")
        face_tag = tag.find("font")
        if face_tag and face_tag.get("face"):
            return face_tag["face"]
        return None

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="html", tier=1)

        doc_fonts = []
        if sidecar:
            doc_fonts = sidecar.get("document_level", {}).get("fonts", [])

        parts: list[str] = []
        parts.append("<!DOCTYPE html>")
        parts.append("<html>")
        parts.append("<head>")
        parts.append(f"<meta charset=\"utf-8\">")
        title = model.metadata.title or model.metadata.source_file
        parts.append(f"<title>{self._escape_html(title)}</title>")
        if doc_fonts:
            font_stack = ", ".join(f"'{f}'" for f in doc_fonts)
            parts.append(f"<style>body {{ font-family: {font_stack}, sans-serif; }}</style>")
        parts.append("</head>")
        parts.append("<body>")

        for elem in model.elements:
            font_style = ""
            font_attr = elem.attributes.get("font_family")
            if font_attr:
                font_style = f' style="font-family: \'{self._escape_html(font_attr)}\'"'

            if elem.type == ElementType.HEADING:
                level = elem.level or 1
                text = self._escape_html(self._strip_md(elem.content))
                parts.append(f"<h{level}{font_style}>{text}</h{level}>")

            elif elem.type == ElementType.PARAGRAPH:
                text = self._escape_html(self._strip_md(elem.content))
                parts.append(f"<p{font_style}>{text}</p>")

            elif elem.type == ElementType.TABLE:
                rows = elem.content
                if isinstance(rows, list) and rows:
                    parts.append("<table border=\"1\">")
                    for i, row in enumerate(rows):
                        if isinstance(row, list):
                            tag = "th" if i == 0 else "td"
                            cells = "".join(f"<{tag}>{self._escape_html(str(c))}</{tag}>" for c in row)
                            parts.append(f"<tr>{cells}</tr>")
                    parts.append("</table>")

            elif elem.type == ElementType.CODE_BLOCK:
                lang = elem.attributes.get("language", "")
                cls = f' class="language-{self._escape_html(lang)}"' if lang else ""
                parts.append(f"<pre><code{cls}>{self._escape_html(elem.content)}</code></pre>")

            elif elem.type == ElementType.BLOCKQUOTE:
                parts.append(f"<blockquote>{self._escape_html(self._strip_md(elem.content))}</blockquote>")

            elif elem.type == ElementType.LIST_ITEM:
                text = self._escape_html(self._strip_md(elem.content))
                parts.append(f"<ul><li>{text}</li></ul>")

            elif elem.type == ElementType.HORIZONTAL_RULE:
                parts.append("<hr>")

            elif elem.type == ElementType.IMAGE:
                src = elem.attributes.get("src", "")
                alt = elem.attributes.get("alt", elem.content)
                parts.append(f'<img src="{self._escape_html(src)}" alt="{self._escape_html(alt)}">')

            elif elem.type == ElementType.FOOTNOTE:
                fn_id = elem.attributes.get("id", "")
                parts.append(f'<aside class="footnote" id="fn-{fn_id}"><small>[{fn_id}] {self._escape_html(elem.content)}</small></aside>')

        parts.append("</body>")
        parts.append("</html>")

        output_path.write_text("\n".join(parts), encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    @staticmethod
    def _escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    @staticmethod
    def _strip_md(text: str) -> str:
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        from bs4 import BeautifulSoup

        raw = self._read_html(file_path)
        soup = BeautifulSoup(raw, "html.parser")
        fonts = self._extract_fonts_from_styles(soup)

        # Also extract font sizes
        sizes = set()
        for tag in soup.find_all(style=True):
            for m in _FONT_SIZE_RE.finditer(tag.get("style", "")):
                sizes.add(m.group(1).strip())

        return {
            "document_level": {
                "extension": ".html",
                "encoding": "utf-8",
                "fonts": fonts,
                "font_sizes": sorted(sizes) if sizes else [],
            }
        }
