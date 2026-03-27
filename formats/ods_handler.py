"""
OpenDocument Spreadsheet handler — ODS files.

Ingest:
  Uses odfpy to parse ODS tables. Each sheet becomes a TABLE element.
  Extracts cell values and font declarations.

Export:
  Generates ODS via odfpy from DocumentModel table elements.
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
class OdsHandler(FormatHandler):
    """OpenDocument Spreadsheet (.ods) handler."""

    EXTENSIONS = ["ods"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        from odf.opendocument import load as odf_load

        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="ods")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="ods",
        )

        doc = odf_load(str(file_path))
        sheets = self._extract_sheets(doc)

        for sheet_name, rows in sheets:
            if rows:
                model.add_element(Element(
                    type=ElementType.TABLE,
                    content=rows,
                    attributes={"sheet_name": sheet_name},
                ))

        # Extract fonts
        fonts = self._extract_fonts(doc)
        if fonts:
            model.style_data["ods_fonts"] = fonts

        model.metadata.page_count = len(sheets) or 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _extract_sheets(self, doc) -> list[tuple[str, list[list[str]]]]:
        sheets: list[tuple[str, list[list[str]]]] = []
        body = doc.body
        for child in body.childNodes:
            if not hasattr(child, "qname"):
                continue
            if child.qname[1] == "spreadsheet":
                for table in child.childNodes:
                    if hasattr(table, "qname") and table.qname[1] == "table":
                        name = table.getAttribute("name") or "Sheet"
                        rows = self._extract_table_rows(table)
                        sheets.append((name, rows))
        return sheets

    def _extract_table_rows(self, table_elem) -> list[list[str]]:
        rows: list[list[str]] = []
        for child in table_elem.childNodes:
            if not hasattr(child, "qname"):
                continue
            if child.qname[1] == "table-row":
                cells: list[str] = []
                for cell in child.childNodes:
                    if hasattr(cell, "qname") and cell.qname[1] == "table-cell":
                        repeat = 1
                        try:
                            rep = cell.getAttribute("numbercolumnsrepeated")
                            if rep:
                                repeat = min(int(rep), 100)
                        except (ValueError, TypeError):
                            pass
                        text = self._get_text(cell).strip()
                        cells.extend([text] * repeat)
                # Trim trailing empty cells
                while cells and not cells[-1]:
                    cells.pop()
                if cells:
                    rows.append(cells)
        return rows

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
                if hasattr(child, "data"):
                    parts.append(child.data or "")
                elif hasattr(child, "childNodes"):
                    parts.append(OdsHandler._get_text(child))
        return "".join(parts)

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableRow, TableCell
        from odf.text import P

        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="ods", tier=1)

        doc = OpenDocumentSpreadsheet()
        tables = model.get_elements_by_type(ElementType.TABLE)

        for i, elem in enumerate(tables):
            sheet_name = elem.attributes.get("sheet_name", f"Sheet{i + 1}")
            table = Table(name=sheet_name)

            rows = elem.content
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, list):
                        tr = TableRow()
                        for cell_val in row:
                            tc = TableCell()
                            p = P()
                            p.addText(str(cell_val))
                            tc.addElement(p)
                            tr.addElement(tc)
                        table.addElement(tr)

            doc.spreadsheet.addElement(table)

        if not tables:
            table = Table(name="Sheet1")
            doc.spreadsheet.addElement(table)

        doc.save(str(output_path))

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        from odf.opendocument import load as odf_load

        doc = odf_load(str(file_path))
        fonts = self._extract_fonts(doc)

        return {
            "document_level": {
                "extension": ".ods",
                "fonts": fonts,
                "default_font": fonts[0] if fonts else "",
            }
        }
