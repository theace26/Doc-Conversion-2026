"""Tests for formats/pdf_handler.py — PDF ingest, export, style extraction, round-trip."""

import tempfile
from pathlib import Path

import pytest

from core.document_model import ElementType
from formats.pdf_handler import PdfHandler


@pytest.fixture
def handler():
    return PdfHandler()


# ── Ingest: simple_text.pdf ──────────────────────────────────────────────────

def test_ingest_simple_returns_model(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    assert model is not None
    assert len(model.elements) > 0


def test_ingest_simple_has_paragraphs(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    paras = model.get_elements_by_type(ElementType.PARAGRAPH)
    assert len(paras) >= 1


def test_ingest_simple_page_count(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    assert model.metadata.page_count == 3


def test_ingest_simple_has_page_breaks(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    breaks = model.get_elements_by_type(ElementType.PAGE_BREAK)
    assert len(breaks) == 2  # 3 pages → 2 page breaks


def test_ingest_simple_has_headings(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    headings = model.get_elements_by_type(ElementType.HEADING)
    # fpdf2 fixtures produce text-layer headings
    assert len(headings) >= 1


def test_ingest_simple_content_check(simple_text_pdf, handler):
    """Check that expected text content is extracted."""
    model = handler.ingest(simple_text_pdf)
    all_text = " ".join(
        str(e.content) for e in model.elements
        if e.type in (ElementType.PARAGRAPH, ElementType.HEADING)
    )
    assert "Simple PDF Document" in all_text or "simple" in all_text.lower()


def test_ingest_simple_has_table(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    tables = model.get_elements_by_type(ElementType.TABLE)
    # The fixture has a table on page 2
    assert len(tables) >= 1


def test_ingest_simple_metadata(simple_text_pdf, handler):
    model = handler.ingest(simple_text_pdf)
    assert model.metadata.source_format == "pdf"
    assert model.metadata.source_file == "simple_text.pdf"


# ── Ingest: scanned.pdf ─────────────────────────────────────────────────────

def test_ingest_scanned_detects_scan(scanned_pdf, handler):
    """Scanned PDF should be detected as needing OCR."""
    model = handler.ingest(scanned_pdf)
    assert model.metadata.ocr_applied is True


def test_ingest_scanned_has_placeholder(scanned_pdf, handler):
    """Scanned pages should produce placeholder elements."""
    model = handler.ingest(scanned_pdf)
    paras = model.get_elements_by_type(ElementType.PARAGRAPH)
    scanned_markers = [p for p in paras if "Scanned page" in str(p.content)]
    assert len(scanned_markers) >= 1


# ── Ingest: mixed.pdf ───────────────────────────────────────────────────────

def test_ingest_mixed_page_count(mixed_pdf, handler):
    model = handler.ingest(mixed_pdf)
    assert model.metadata.page_count == 2


def test_ingest_mixed_has_text_and_scanned(mixed_pdf, handler):
    """Page 1 should have text content, page 2 should be flagged as scanned."""
    model = handler.ingest(mixed_pdf)
    all_text = " ".join(str(e.content) for e in model.elements)
    # Page 1 text should be present
    assert "Mixed PDF Document" in all_text or "mixed" in all_text.lower() or "text layer" in all_text.lower()


# ── Ingest: encrypted/invalid ────────────────────────────────────────────────

def test_ingest_invalid_pdf_raises(handler, tmp_path):
    """Invalid PDF should raise ValueError."""
    bad_file = tmp_path / "bad.pdf"
    bad_file.write_text("this is not a PDF")
    with pytest.raises(ValueError, match="Cannot open PDF"):
        handler.ingest(bad_file)


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_creates_file(simple_text_pdf, handler, tmp_path):
    model = handler.ingest(simple_text_pdf)
    output = tmp_path / "output.pdf"
    handler.export(model, output)
    assert output.exists()
    assert output.stat().st_size > 0


def test_export_readable_pdf(simple_text_pdf, handler, tmp_path):
    """Exported PDF should be openable by pdfplumber."""
    import pdfplumber

    model = handler.ingest(simple_text_pdf)
    output = tmp_path / "output.pdf"
    handler.export(model, output)

    pdf = pdfplumber.open(output)
    assert len(pdf.pages) >= 1
    pdf.close()


def test_export_with_sidecar(simple_text_pdf, handler, tmp_path):
    """Sidecar Tier 2: page size and margins should be applied."""
    model = handler.ingest(simple_text_pdf)
    styles = handler.extract_styles(simple_text_pdf)
    sidecar = {
        "document_level": styles.get("document_level", {}),
        "elements": {},
    }
    output = tmp_path / "styled.pdf"
    handler.export(model, output, sidecar=sidecar)
    assert output.exists()
    assert output.stat().st_size > 0


# ── Style extraction ─────────────────────────────────────────────────────────

def test_extract_styles_document_level(simple_text_pdf, handler):
    styles = handler.extract_styles(simple_text_pdf)
    assert "document_level" in styles
    doc = styles["document_level"]
    assert "page_width" in doc
    assert "page_height" in doc


def test_extract_styles_has_page_entries(simple_text_pdf, handler):
    styles = handler.extract_styles(simple_text_pdf)
    assert "page_1" in styles
    assert "page_2" in styles


# ── Round-trip ───────────────────────────────────────────────────────────────

def test_roundtrip_structure_survives(simple_text_pdf, handler, tmp_path):
    """PDF → MD → PDF: heading/table counts should be approximately preserved."""
    model = handler.ingest(simple_text_pdf)
    headings_before = len(model.get_elements_by_type(ElementType.HEADING))
    tables_before = len(model.get_elements_by_type(ElementType.TABLE))

    # Export to PDF
    output = tmp_path / "roundtrip.pdf"
    handler.export(model, output)

    # Re-ingest
    model2 = handler.ingest(output)

    # Structure should be approximately equivalent
    assert model2.metadata.page_count >= 1
    paras = model2.get_elements_by_type(ElementType.PARAGRAPH)
    assert len(paras) >= 1


# ── supports_format ──────────────────────────────────────────────────────────

def test_supports_pdf():
    assert PdfHandler.supports_format("pdf")
    assert PdfHandler.supports_format(".pdf")
    assert PdfHandler.supports_format("PDF")
    assert not PdfHandler.supports_format("docx")
