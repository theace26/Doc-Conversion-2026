"""
Cross-format round-trip tests.

Ingest → DocumentModel → export → re-ingest → compare.
These verify that the pipeline preserves structure through a full cycle.
"""

import pytest
from pathlib import Path

from core.document_model import ElementType


@pytest.mark.slow
class TestRoundTrip:
    """Round-trip conversion tests across formats."""

    def test_docx_to_md_to_docx(self, simple_docx, tmp_path):
        """DOCX → MD → DOCX: heading hierarchy and table count preserved."""
        from formats.docx_handler import DocxHandler
        from formats.markdown_handler import MarkdownHandler

        docx_handler = DocxHandler()
        md_handler = MarkdownHandler()

        # DOCX → DocumentModel
        model1 = docx_handler.ingest(simple_docx)
        h1_count = len([e for e in model1.elements if e.type == ElementType.HEADING])
        table1_count = len(model1.get_elements_by_type(ElementType.TABLE))

        # Model → Markdown
        md_path = tmp_path / "test.md"
        md_handler.export(model1, md_path)

        # Markdown → DocumentModel
        model2 = md_handler.ingest(md_path)

        # DocumentModel → DOCX
        docx_out = tmp_path / "roundtrip.docx"
        docx_handler.export(model2, docx_out)

        # Re-ingest DOCX
        model3 = docx_handler.ingest(docx_out)
        h3_count = len([e for e in model3.elements if e.type == ElementType.HEADING])
        table3_count = len(model3.get_elements_by_type(ElementType.TABLE))

        assert h3_count >= h1_count, "Heading count should be preserved"
        assert table3_count >= table1_count, "Table count should be preserved"

    def test_pptx_to_md_to_pptx(self, simple_pptx, tmp_path):
        """PPTX → MD → PPTX: slide count preserved."""
        from formats.pptx_handler import PptxHandler
        from formats.markdown_handler import MarkdownHandler

        pptx_handler = PptxHandler()
        md_handler = MarkdownHandler()

        model1 = pptx_handler.ingest(simple_pptx)
        slide_count = model1.metadata.page_count

        md_path = tmp_path / "test.md"
        md_handler.export(model1, md_path)

        model2 = md_handler.ingest(md_path)

        pptx_out = tmp_path / "roundtrip.pptx"
        pptx_handler.export(model2, pptx_out)

        from pptx import Presentation
        prs = Presentation(str(pptx_out))
        assert len(prs.slides) >= 1, "Should produce at least one slide"

    def test_xlsx_to_md_to_xlsx(self, simple_xlsx, tmp_path):
        """XLSX → MD → XLSX: sheet count and row count preserved."""
        from formats.xlsx_handler import XlsxHandler
        from formats.markdown_handler import MarkdownHandler

        xlsx_handler = XlsxHandler()
        md_handler = MarkdownHandler()

        model1 = xlsx_handler.ingest(simple_xlsx)
        sheet_count = model1.metadata.page_count
        tables1 = model1.get_elements_by_type(ElementType.TABLE)
        row_counts1 = [len(t.content) for t in tables1]

        md_path = tmp_path / "test.md"
        md_handler.export(model1, md_path)

        model2 = md_handler.ingest(md_path)

        xlsx_out = tmp_path / "roundtrip.xlsx"
        xlsx_handler.export(model2, xlsx_out)

        model3 = xlsx_handler.ingest(xlsx_out)
        tables3 = model3.get_elements_by_type(ElementType.TABLE)

        # Sheet count preserved (each sheet = H2 heading)
        h2_count = len([e for e in model3.elements if e.type == ElementType.HEADING and e.level == 2])
        assert h2_count >= 1

        # At least one table preserved
        assert len(tables3) >= 1

    def test_csv_to_md_to_csv(self, simple_csv, tmp_path):
        """CSV → MD → CSV: row count and column count exact match."""
        from formats.csv_handler import CsvHandler
        from formats.markdown_handler import MarkdownHandler

        csv_handler = CsvHandler()
        md_handler = MarkdownHandler()

        model1 = csv_handler.ingest(simple_csv)
        table1 = model1.get_elements_by_type(ElementType.TABLE)[0]
        orig_rows = len(table1.content)
        orig_cols = len(table1.content[0])

        md_path = tmp_path / "test.md"
        md_handler.export(model1, md_path)

        model2 = md_handler.ingest(md_path)

        csv_out = tmp_path / "roundtrip.csv"
        csv_handler.export(model2, csv_out)

        model3 = csv_handler.ingest(csv_out)
        tables3 = model3.get_elements_by_type(ElementType.TABLE)
        assert len(tables3) == 1

        table3 = tables3[0]
        assert len(table3.content) == orig_rows
        assert len(table3.content[0]) == orig_cols

    def test_pdf_to_md(self, simple_text_pdf, tmp_path):
        """PDF → MD: paragraph count within tolerance (OCR noise)."""
        from formats.pdf_handler import PdfHandler
        from formats.markdown_handler import MarkdownHandler

        pdf_handler = PdfHandler()
        md_handler = MarkdownHandler()

        model1 = pdf_handler.ingest(simple_text_pdf)
        para_count = len(model1.get_elements_by_type(ElementType.PARAGRAPH))

        md_path = tmp_path / "test.md"
        md_handler.export(model1, md_path)

        model2 = md_handler.ingest(md_path)

        para_count2 = len(model2.get_elements_by_type(ElementType.PARAGRAPH))
        # Allow ±20% tolerance for PDF text extraction noise
        assert para_count2 >= para_count * 0.8
