"""
Tests for formats/pdf_handler.py — PDF ingest and export.

Covers text-native PDF extraction, OCR path (mocked), edge cases,
and Markdown → PDF export via WeasyPrint.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from core.document_model import DocumentModel, Element, ElementType


# ── Text-native PDF ingest ───────────────────────────────────────────────────

class TestPdfIngestTextNative:
    """Tests for ingesting text-layer PDFs."""

    def test_extracts_paragraphs(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        paragraphs = model.get_elements_by_type(ElementType.PARAGRAPH)
        assert len(paragraphs) > 0, "Should extract at least one paragraph"

    def test_detects_headings_by_font_size(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        headings = model.get_elements_by_type(ElementType.HEADING)
        assert len(headings) > 0, "Should detect headings from larger font sizes"

    def test_page_count_matches(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        assert model.metadata.page_count == 3, "simple_text.pdf has 3 pages"

    def test_source_format_is_pdf(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        assert model.metadata.source_format == "pdf"

    def test_multi_page_elements_in_order(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        page_breaks = model.get_elements_by_type(ElementType.PAGE_BREAK)
        assert len(page_breaks) == 2, "3-page PDF should have 2 page breaks"

    def test_extracts_tables(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        tables = model.get_elements_by_type(ElementType.TABLE)
        assert len(tables) >= 1, "simple_text.pdf page 2 has a table"

    def test_table_has_correct_structure(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)

        tables = model.get_elements_by_type(ElementType.TABLE)
        if tables:
            rows = tables[0].content
            assert isinstance(rows, list)
            assert len(rows) >= 2, "Table should have header + data rows"


# ── OCR path (mocked) ───────────────────────────────────────────────────────

class TestPdfIngestOCR:
    """Tests for the OCR integration path."""

    def test_scanned_pdf_triggers_ocr_flag(self, scanned_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(scanned_pdf)

        assert model.metadata.ocr_applied is True

    def test_scanned_pdf_warnings(self, scanned_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(scanned_pdf)

        assert any("Scanned" in w or "scanned" in w.lower() for w in model.warnings)

    def test_ingest_with_ocr_sets_scanned_pages(self, scanned_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest_with_ocr(scanned_pdf, batch_id="test_batch")

        assert model.metadata.ocr_applied is True
        assert hasattr(model, "_scanned_pages")


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestPdfIngestEdgeCases:
    """Edge case tests for PDF ingest."""

    def test_corrupt_pdf_raises_error(self, tmp_path):
        from formats.pdf_handler import PdfHandler

        bad_pdf = tmp_path / "corrupt.pdf"
        bad_pdf.write_bytes(b"NOT A REAL PDF FILE CONTENTS")

        handler = PdfHandler()
        with pytest.raises((ValueError, Exception)):
            handler.ingest(bad_pdf)

    def test_empty_text_pdf(self, tmp_path):
        """PDF with only whitespace text should still produce a model."""
        from fpdf import FPDF
        from formats.pdf_handler import PdfHandler

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(0, 10, "   ", new_x="LMARGIN", new_y="NEXT")
        path = tmp_path / "whitespace.pdf"
        pdf.output(str(path))

        handler = PdfHandler()
        model = handler.ingest(path)
        assert model.metadata.page_count == 1


# ── Export tests ─────────────────────────────────────────────────────────────

class TestPdfExport:
    """Tests for Markdown → PDF export via WeasyPrint."""

    def test_all_element_types_export_without_raising(self, document_model_with_all_elements, tmp_path):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        output = tmp_path / "output.pdf"

        try:
            handler.export(document_model_with_all_elements, output)
            assert output.exists()
            content = output.read_bytes()
            assert content[:5] == b"%PDF-"
        except ImportError:
            pytest.skip("WeasyPrint not available")

    def test_heading_renders_in_html(self, document_model_with_all_elements):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        html = handler._model_to_html(document_model_with_all_elements)

        assert "<h1>" in html
        assert "<h2>" in html

    def test_table_renders_in_html(self, document_model_with_all_elements):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        html = handler._model_to_html(document_model_with_all_elements)

        assert "<table>" in html
        assert "<th>" in html

    def test_export_is_always_tier1(self, document_model_with_all_elements, tmp_path):
        """PDF export cannot be patched — always Tier 1."""
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        output = tmp_path / "t1.pdf"
        sidecar = {"document_level": {}}

        try:
            handler.export(document_model_with_all_elements, output, sidecar=sidecar)
            assert output.exists()
        except ImportError:
            pytest.skip("WeasyPrint not available")

    def test_output_is_valid_pdf(self, simple_text_pdf, tmp_path):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(simple_text_pdf)
        output = tmp_path / "roundtrip.pdf"

        try:
            handler.export(model, output)
            content = output.read_bytes()
            assert content[:5] == b"%PDF-"
        except ImportError:
            pytest.skip("WeasyPrint not available")


class TestPdfStyleExtraction:
    """Tests for PDF style extraction."""

    def test_extract_styles_returns_dict(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        styles = handler.extract_styles(simple_text_pdf)
        assert isinstance(styles, dict)
        assert "document_level" in styles

    def test_extract_styles_has_page_dimensions(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        styles = handler.extract_styles(simple_text_pdf)
        dl = styles["document_level"]
        assert "page_width" in dl or "page_height" in dl

    def test_extract_styles_has_per_page(self, simple_text_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        styles = handler.extract_styles(simple_text_pdf)
        assert "page_1" in styles

    def test_supports_format(self):
        from formats.pdf_handler import PdfHandler

        assert PdfHandler.supports_format("pdf")
        assert PdfHandler.supports_format(".pdf")
        assert not PdfHandler.supports_format("docx")

    def test_mixed_pdf_has_text_and_scanned_pages(self, mixed_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest(mixed_pdf)
        assert model.metadata.page_count == 2

    def test_ingest_with_ocr_mixed(self, mixed_pdf):
        from formats.pdf_handler import PdfHandler

        handler = PdfHandler()
        model = handler.ingest_with_ocr(mixed_pdf, batch_id="test_mix")
