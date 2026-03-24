"""
PDF format handler — text extraction, OCR integration, and WeasyPrint export.

Ingest:
  - Text-layer PDFs → pdfplumber text + table extraction
  - Scanned pages → OCR via core/ocr.run_ocr()
  - Mixed documents handled page-by-page

Export:
  - DocumentModel → HTML → PDF via WeasyPrint
  - Sidecar Tier 2: page size, margins, fonts applied as CSS
  - Tier 3 not supported (PDF internal structure too complex to patch)
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
    compute_content_hash,
)

log = structlog.get_logger(__name__)

# Minimum text length per page to consider it a "text" page (not scanned)
_MIN_TEXT_LENGTH = 50


@register_handler
class PdfHandler(FormatHandler):
    EXTENSIONS = ["pdf"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        import pdfplumber

        t_start = time.perf_counter()
        log.info("handler_ingest_start", filename=file_path.name, format="pdf")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="pdf",
        )

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as exc:
            raise ValueError(f"Cannot open PDF: {exc}") from exc

        page_count = len(pdf.pages)
        model.metadata.page_count = page_count
        scanned_page_nums: list[int] = []

        for idx, page in enumerate(pdf.pages):
            page_num = idx + 1

            # Add page break between pages (not before first)
            if idx > 0:
                model.add_element(Element(type=ElementType.PAGE_BREAK, content=""))

            # Try text extraction
            text = (page.extract_text() or "").strip()
            tables = page.extract_tables() or []

            is_scanned = len(text) < _MIN_TEXT_LENGTH and _page_has_content(page)

            if is_scanned:
                scanned_page_nums.append(page_num)
                model.add_element(
                    Element(
                        type=ElementType.PARAGRAPH,
                        content=f"[Scanned page {page_num}]",
                        attributes={"ocr_page": page_num, "scanned": True},
                    )
                )
                if text:
                    model.add_element(
                        Element(type=ElementType.PARAGRAPH, content=text)
                    )
            else:
                self._extract_text_elements(model, text, tables, page_num, page)

            self._extract_page_images(model, page, file_path, page_num)

        pdf.close()

        if scanned_page_nums:
            model.metadata.ocr_applied = True
            model.warnings.append(
                f"Scanned pages detected: {scanned_page_nums}. "
                "OCR was not run (requires async context). "
                "Use ingest_with_ocr() for full OCR support."
            )

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
        )
        return model

    def ingest_with_ocr(
        self,
        file_path: Path,
        ocr_config: Any = None,
        batch_id: str = "",
    ) -> DocumentModel:
        """
        Full ingest with OCR for scanned pages.

        Synchronous wrapper — OCR pages are stored on the model for the caller
        to process via core.ocr.run_ocr() in an async context.
        """
        import pdfplumber

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="pdf",
        )

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as exc:
            raise ValueError(f"Cannot open PDF: {exc}") from exc

        page_count = len(pdf.pages)
        model.metadata.page_count = page_count
        scanned_pages: list[tuple[int, Any]] = []

        for idx, page in enumerate(pdf.pages):
            page_num = idx + 1

            if idx > 0:
                model.add_element(Element(type=ElementType.PAGE_BREAK, content=""))

            text = (page.extract_text() or "").strip()
            tables = page.extract_tables() or []

            is_scanned = len(text) < _MIN_TEXT_LENGTH and _page_has_content(page)

            if is_scanned:
                try:
                    from pdf2image import convert_from_path

                    images = convert_from_path(
                        str(file_path),
                        first_page=page_num,
                        last_page=page_num,
                        dpi=300,
                    )
                    if images:
                        scanned_pages.append((page_num, images[0]))
                        model.metadata.ocr_applied = True
                except Exception as exc:
                    log.warning("pdf.ocr_page_convert_failed", page=page_num, error=str(exc))
                    if text:
                        model.add_element(
                            Element(type=ElementType.PARAGRAPH, content=text)
                        )
            else:
                self._extract_text_elements(model, text, tables, page_num, page)

            self._extract_page_images(model, page, file_path, page_num)

        pdf.close()

        model.metadata.ocr_applied = bool(scanned_pages)
        if scanned_pages:
            model._scanned_pages = scanned_pages  # type: ignore[attr-defined]

        return model

    def _extract_text_elements(
        self,
        model: DocumentModel,
        text: str,
        tables: list,
        page_num: int,
        page: Any = None,
    ) -> None:
        """Extract paragraphs and tables from a text-layer page."""
        table_texts: set[str] = set()
        for table_data in tables:
            if not table_data or not table_data[0]:
                continue
            rows: list[list[str]] = []
            for row in table_data:
                rows.append([str(cell) if cell else "" for cell in row])
            if rows:
                model.add_element(Element(type=ElementType.TABLE, content=rows))
                for row in rows:
                    for cell in row:
                        if cell.strip():
                            table_texts.add(cell.strip())

        if not text:
            return

        # Build font-size map from char-level data to detect headings
        line_font_sizes: dict[int, float] = {}
        body_font_size = 12.0
        if page and hasattr(page, "chars") and page.chars:
            line_chars: dict[float, list[float]] = {}
            for c in page.chars:
                top = round(c["top"], 0)
                line_chars.setdefault(top, []).append(c.get("size", 12.0))
            # Sort by y position and assign line indices
            sorted_tops = sorted(line_chars.keys())
            for li, top in enumerate(sorted_tops):
                sizes = line_chars[top]
                line_font_sizes[li] = max(sizes) if sizes else 12.0
            # Body font size = most common size
            all_sizes = [s for sizes in line_chars.values() for s in sizes]
            if all_sizes:
                size_counts: dict[float, int] = {}
                for s in all_sizes:
                    rs = round(s, 1)
                    size_counts[rs] = size_counts.get(rs, 0) + 1
                body_font_size = max(size_counts, key=size_counts.get)  # type: ignore[arg-type]

        # Split text into lines, then group into paragraphs
        lines = text.split("\n")
        paragraphs: list[str] = []
        current_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_lines:
                    paragraphs.append(" ".join(current_lines))
                    current_lines = []
                continue
            current_lines.append(stripped)

        if current_lines:
            paragraphs.append(" ".join(current_lines))

        # If we only got one big paragraph, try line-by-line approach
        # using font sizes to detect headings vs body
        if len(paragraphs) <= 1 and lines:
            paragraphs = []
            line_idx = 0
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    line_idx += 1
                    continue
                if stripped in table_texts:
                    line_idx += 1
                    continue

                font_size = line_font_sizes.get(line_idx, body_font_size)
                is_heading = font_size > body_font_size + 1.0

                if is_heading:
                    level = 1 if font_size > body_font_size + 4.0 else 2
                    model.add_element(
                        Element(type=ElementType.HEADING, content=stripped, level=level)
                    )
                else:
                    model.add_element(
                        Element(type=ElementType.PARAGRAPH, content=stripped)
                    )
                line_idx += 1
            return

        for para in paragraphs:
            para = para.strip()
            if not para or para in table_texts:
                continue

            if self._looks_like_heading(para):
                level = 1 if len(para) < 30 else 2
                model.add_element(
                    Element(type=ElementType.HEADING, content=para, level=level)
                )
            else:
                model.add_element(
                    Element(type=ElementType.PARAGRAPH, content=para)
                )

    def _looks_like_heading(self, text: str) -> bool:
        lines = text.strip().split("\n")
        if len(lines) > 2:
            return False
        first = lines[0].strip()
        if not first:
            return False
        if len(first) < 80 and not first.endswith((".", ",", ";", ":", "!")):
            if first.isupper() and len(first) > 2:
                return True
            if len(first) < 60 and first.istitle():
                return True
        return False

    def _extract_page_images(
        self, model: DocumentModel, page: Any, file_path: Path, page_num: int
    ) -> None:
        from core.image_handler import extract_image
        from core.document_model import ImageData

        try:
            if not hasattr(page, "images") or not page.images:
                return
            for img_info in page.images:
                if hasattr(img_info, "get") and "stream" in img_info:
                    raw = img_info["stream"].get_data()
                    if raw and len(raw) > 100:
                        hash_name, png_data, meta = extract_image(raw, "png")
                        model.images[hash_name] = ImageData(
                            data=png_data,
                            original_format="pdf_embedded",
                            width=meta.get("width"),
                            height=meta.get("height"),
                        )
                        model.add_element(
                            Element(
                                type=ElementType.IMAGE,
                                content=f"assets/{hash_name}",
                                attributes={"page": page_num},
                            )
                        )
        except Exception as exc:
            log.debug("pdf.image_extract_failed", page=page_num, error=str(exc))

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="pdf", tier=1)

        html = self._model_to_html(model, sidecar)
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(output_path))

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, output_path=str(output_path), duration_ms=duration_ms)

    def _model_to_html(self, model: DocumentModel, sidecar: dict[str, Any] | None = None) -> str:
        parts: list[str] = []
        page_css = self._build_page_css(sidecar)

        parts.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
        parts.append(f"<style>{page_css}</style>")
        parts.append("</head><body>")

        for elem in model.elements:
            parts.append(self._render_element_html(elem, model))

        parts.append("</body></html>")
        return "\n".join(parts)

    def _build_page_css(self, sidecar: dict[str, Any] | None) -> str:
        css_parts = [
            "body { font-family: serif; font-size: 12pt; line-height: 1.5; margin: 0; padding: 0; }",
            "table { border-collapse: collapse; width: 100%; margin: 1em 0; }",
            "td, th { border: 1px solid #999; padding: 6px 10px; text-align: left; }",
            "th { background: #f0f0f0; font-weight: bold; }",
            "pre { background: #f5f5f5; padding: 1em; overflow-x: auto; font-size: 10pt; }",
            "code { font-family: monospace; }",
            "blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }",
            "img { max-width: 100%; height: auto; }",
        ]

        if sidecar:
            doc_level = sidecar.get("document_level", {})
            mt = doc_level.get("margin_top", "2.54cm")
            mb = doc_level.get("margin_bottom", "2.54cm")
            ml = doc_level.get("margin_left", "2.54cm")
            mr = doc_level.get("margin_right", "2.54cm")
            pw = doc_level.get("page_width", "")
            ph = doc_level.get("page_height", "")
            page_size = f"{pw} {ph}" if pw and ph else "A4"
            css_parts.append(f"@page {{ size: {page_size}; margin: {mt} {mr} {mb} {ml}; }}")

            default_font = doc_level.get("default_font", "")
            if default_font:
                css_parts[0] = css_parts[0].replace(
                    "font-family: serif;", f"font-family: '{default_font}', serif;"
                )
        else:
            css_parts.append("@page { size: A4; margin: 2.54cm; }")

        return "\n".join(css_parts)

    def _render_element_html(self, elem: Element, model: DocumentModel) -> str:
        if elem.type == ElementType.HEADING:
            level = min(elem.level or 1, 6)
            return f"<h{level}>{_escape_html(str(elem.content))}</h{level}>"

        if elem.type == ElementType.PARAGRAPH:
            return f"<p>{_inline_md_to_html(str(elem.content))}</p>"

        if elem.type == ElementType.TABLE:
            return self._render_table_html(elem.content)

        if elem.type == ElementType.IMAGE:
            src = str(elem.content)
            img_name = Path(src).name
            if img_name in model.images:
                import base64
                b64 = base64.b64encode(model.images[img_name].data).decode()
                alt = _escape_html(model.images[img_name].alt_text)
                return f'<img src="data:image/png;base64,{b64}" alt="{alt}">'
            return f'<img src="{_escape_html(src)}">'

        if elem.type == ElementType.CODE_BLOCK:
            return f"<pre><code>{_escape_html(str(elem.content))}</code></pre>"

        if elem.type == ElementType.BLOCKQUOTE:
            return f"<blockquote><p>{_inline_md_to_html(str(elem.content))}</p></blockquote>"

        if elem.type == ElementType.LIST:
            tag = "ol" if elem.attributes.get("ordered") else "ul"
            items = ""
            if elem.children:
                for child in elem.children:
                    items += f"<li>{_inline_md_to_html(str(child.content))}</li>\n"
            return f"<{tag}>\n{items}</{tag}>"

        if elem.type == ElementType.LIST_ITEM:
            return f"<li>{_inline_md_to_html(str(elem.content))}</li>"

        if elem.type == ElementType.HORIZONTAL_RULE:
            return "<hr>"

        if elem.type == ElementType.PAGE_BREAK:
            return '<div style="page-break-before: always"></div>'

        if elem.type == ElementType.FOOTNOTE:
            fid = elem.attributes.get("id", "")
            text = _inline_md_to_html(str(elem.content))
            return f'<div class="footnote" id="fn-{_escape_html(str(fid))}"><sup>{_escape_html(str(fid))}</sup> {text}</div>'

        if elem.type == ElementType.RAW_HTML:
            return str(elem.content)

        return f"<p>{_escape_html(str(elem.content))}</p>"

    def _render_table_html(self, rows: list[list[str]]) -> str:
        if not rows:
            return ""
        html = "<table>\n<thead>\n<tr>"
        for cell in rows[0]:
            html += f"<th>{_escape_html(str(cell))}</th>"
        html += "</tr>\n</thead>\n<tbody>\n"
        for row in rows[1:]:
            html += "<tr>"
            for cell in row:
                html += f"<td>{_escape_html(str(cell))}</td>"
            html += "</tr>\n"
        html += "</tbody>\n</table>"
        return html

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        import pdfplumber

        styles: dict[str, Any] = {"document_level": {}}

        try:
            pdf = pdfplumber.open(file_path)
        except Exception:
            return styles

        if pdf.pages:
            first = pdf.pages[0]
            styles["document_level"]["page_width"] = f"{first.width}pt"
            styles["document_level"]["page_height"] = f"{first.height}pt"

            if first.chars:
                xs = [c["x0"] for c in first.chars]
                ys = [c["top"] for c in first.chars]
                x1s = [c["x1"] for c in first.chars]
                y1s = [c["bottom"] for c in first.chars]
                styles["document_level"]["margin_left"] = f"{min(xs):.1f}pt"
                styles["document_level"]["margin_top"] = f"{min(ys):.1f}pt"
                styles["document_level"]["margin_right"] = f"{first.width - max(x1s):.1f}pt"
                styles["document_level"]["margin_bottom"] = f"{first.height - max(y1s):.1f}pt"

            fonts_seen: dict[str, int] = {}
            for char in first.chars:
                fname = char.get("fontname", "")
                if fname:
                    fonts_seen[fname] = fonts_seen.get(fname, 0) + 1
            if fonts_seen:
                styles["document_level"]["default_font"] = max(
                    fonts_seen, key=fonts_seen.get  # type: ignore[arg-type]
                )

        for idx, page in enumerate(pdf.pages):
            key = f"page_{idx + 1}"
            page_style: dict[str, Any] = {"width": page.width, "height": page.height}
            if hasattr(page, "rotation"):
                page_style["rotation"] = page.rotation
            styles[key] = page_style

        pdf.close()
        return styles

    @classmethod
    def supports_format(cls, extension: str) -> bool:
        return extension.lower().lstrip(".") in cls.EXTENSIONS


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _inline_md_to_html(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def _page_has_content(page: Any) -> bool:
    if page.chars:
        return True
    if page.images:
        return True
    if page.lines or page.rects:
        return True
    return False
