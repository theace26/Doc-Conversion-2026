"""
XML format handler — structured XML data extraction.

Ingest:
  Parses XML tree structure. Root element becomes heading, child
  elements become paragraphs or tables depending on structure.
  Handles common corporate XML formats (data exports, configs).

Export:
  Generates well-formed XML from DocumentModel elements.
"""

import re
import time
import xml.etree.ElementTree as ET
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

_ENCODINGS = ["utf-8", "cp1252", "latin-1"]


@register_handler
class XmlHandler(FormatHandler):
    """XML data file handler."""

    EXTENSIONS = ["xml"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="xml")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="xml",
        )

        raw = self._read_xml(file_path)
        if not raw.strip():
            model.warnings.append("Empty XML file.")
            return model

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            model.warnings.append(f"XML parse error: {exc}")
            # Fall back to raw text
            for line in raw.split("\n"):
                line = line.strip()
                if line and not line.startswith("<?"):
                    model.add_element(Element(type=ElementType.PARAGRAPH, content=line))
            return model

        # Root tag as heading
        root_tag = self._clean_tag(root.tag)
        model.add_element(Element(
            type=ElementType.HEADING,
            content=root_tag,
            level=1,
        ))

        # Check if this is tabular data (all children have same tag)
        child_tags = [self._clean_tag(child.tag) for child in root]
        if child_tags and len(set(child_tags)) == 1 and len(child_tags) > 1:
            # Tabular: treat as rows
            rows = self._extract_table(root)
            if rows:
                model.add_element(Element(type=ElementType.TABLE, content=rows))
        else:
            # Hierarchical: walk tree
            self._walk_element(root, model, depth=1)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _read_xml(self, file_path: Path) -> str:
        raw_bytes = file_path.read_bytes()
        for enc in _ENCODINGS:
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw_bytes.decode("latin-1")

    def _walk_element(self, elem: ET.Element, model: DocumentModel, depth: int) -> None:
        """Recursively walk XML tree, creating elements."""
        for child in elem:
            tag = self._clean_tag(child.tag)
            text = (child.text or "").strip()
            tail = (child.tail or "").strip()

            has_children = len(child) > 0

            if has_children:
                # Section heading
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=tag,
                    level=min(depth + 1, 6),
                ))
                if text:
                    model.add_element(Element(type=ElementType.PARAGRAPH, content=text))
                self._walk_element(child, model, depth + 1)
            else:
                # Leaf node: "tag: value"
                if text:
                    model.add_element(Element(
                        type=ElementType.PARAGRAPH,
                        content=f"{tag}: {text}",
                    ))

            if tail:
                model.add_element(Element(type=ElementType.PARAGRAPH, content=tail))

    def _extract_table(self, root: ET.Element) -> list[list[str]]:
        """Extract tabular XML (same-tag children) as rows."""
        rows: list[list[str]] = []
        headers: list[str] = []

        for child in root:
            row_data: list[str] = []
            for field in child:
                tag = self._clean_tag(field.tag)
                if not headers or tag not in headers:
                    if len(rows) == 0:
                        headers.append(tag)
                text = (field.text or "").strip()
                row_data.append(text)

            if not rows:
                rows.append(headers)
            rows.append(row_data)

        return rows

    @staticmethod
    def _clean_tag(tag: str) -> str:
        """Remove namespace prefix from XML tag."""
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="xml", tier=1)

        root_name = "document"
        # Try to use first heading as root name
        headings = model.get_elements_by_type(ElementType.HEADING)
        if headings:
            root_name = re.sub(r"[^a-zA-Z0-9_-]", "_", headings[0].content)

        root = ET.Element(root_name)

        # Tables → structured XML
        tables = model.get_elements_by_type(ElementType.TABLE)
        if tables:
            for table_elem in tables:
                rows = table_elem.content
                if isinstance(rows, list) and len(rows) > 1:
                    headers = rows[0] if rows else []
                    for row in rows[1:]:
                        if isinstance(row, list):
                            record = ET.SubElement(root, "record")
                            for i, val in enumerate(row):
                                tag = re.sub(r"[^a-zA-Z0-9_-]", "_", headers[i]) if i < len(headers) else f"field{i}"
                                field = ET.SubElement(record, tag or "field")
                                field.text = str(val)
        else:
            # Non-table content → paragraphs as elements
            for elem in model.elements:
                if elem.type == ElementType.HEADING:
                    section = ET.SubElement(root, "section")
                    section.set("title", self._strip_md(elem.content))
                elif elem.type == ElementType.PARAGRAPH:
                    p = ET.SubElement(root, "paragraph")
                    p.text = self._strip_md(elem.content)

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(str(output_path), encoding="unicode", xml_declaration=True)

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
        raw = self._read_xml(file_path)
        encoding = "utf-8"
        # Detect XML declaration encoding
        m = re.match(r'<\?xml[^>]*encoding=["\']([^"\']+)', raw)
        if m:
            encoding = m.group(1)

        return {
            "document_level": {
                "extension": ".xml",
                "encoding": encoding,
                "font_family": "monospace",
                "font_name": "Courier New",
            }
        }
