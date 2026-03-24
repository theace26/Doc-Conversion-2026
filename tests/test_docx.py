"""Tests for formats/docx_handler.py — DOCX ingest, style extraction, export."""

import io
from pathlib import Path

import pytest

from core.document_model import ElementType
from formats.docx_handler import DocxHandler


@pytest.fixture
def handler():
    return DocxHandler()


# ── Ingest: simple.docx ───────────────────────────────────────────────────────

def test_ingest_simple_returns_model(simple_docx, handler):
    model = handler.ingest(simple_docx)
    assert model is not None
    assert len(model.elements) > 0


def test_ingest_simple_has_headings(simple_docx, handler):
    model = handler.ingest(simple_docx)
    headings = model.get_elements_by_type(ElementType.HEADING)
    assert len(headings) >= 3  # H1, H2, H3


def test_ingest_simple_heading_levels(simple_docx, handler):
    model = handler.ingest(simple_docx)
    headings = model.get_elements_by_type(ElementType.HEADING)
    levels = {h.level for h in headings}
    assert 1 in levels
    assert 2 in levels
    assert 3 in levels


def test_ingest_simple_heading_content(simple_docx, handler):
    model = handler.ingest(simple_docx)
    headings = model.get_elements_by_type(ElementType.HEADING)
    heading_texts = [h.content for h in headings]
    assert "Simple Document" in heading_texts


def test_ingest_simple_has_paragraphs(simple_docx, handler):
    model = handler.ingest(simple_docx)
    paras = model.get_elements_by_type(ElementType.PARAGRAPH)
    assert len(paras) >= 2


def test_ingest_simple_has_table(simple_docx, handler):
    model = handler.ingest(simple_docx)
    tables = model.get_elements_by_type(ElementType.TABLE)
    assert len(tables) >= 1


def test_ingest_simple_table_dimensions(simple_docx, handler):
    model = handler.ingest(simple_docx)
    tables = model.get_elements_by_type(ElementType.TABLE)
    table = tables[0]
    assert isinstance(table.content, list)
    assert len(table.content) == 3  # 3 rows
    assert len(table.content[0]) == 3  # 3 cols


def test_ingest_simple_table_header_content(simple_docx, handler):
    model = handler.ingest(simple_docx)
    tables = model.get_elements_by_type(ElementType.TABLE)
    header_row = tables[0].content[0]
    assert "Column A" in header_row
    assert "Column B" in header_row
    assert "Column C" in header_row


def test_ingest_simple_has_image(simple_docx, handler):
    model = handler.ingest(simple_docx)
    images = model.get_elements_by_type(ElementType.IMAGE)
    assert len(images) >= 1


def test_ingest_simple_image_has_hash_filename(simple_docx, handler):
    model = handler.ingest(simple_docx)
    assert len(model.images) >= 1
    for fname in model.images:
        assert fname.endswith(".png")
        assert len(fname) > 5  # hash + extension


def test_ingest_simple_metadata(simple_docx, handler):
    model = handler.ingest(simple_docx)
    assert model.metadata.source_format == "docx"
    assert model.metadata.source_file != ""


# ── Ingest: complex.docx ──────────────────────────────────────────────────────

def test_ingest_complex_returns_model(complex_docx, handler):
    model = handler.ingest(complex_docx)
    assert len(model.elements) > 0


def test_ingest_complex_has_multiple_images(complex_docx, handler):
    model = handler.ingest(complex_docx)
    assert len(model.images) >= 2


def test_ingest_complex_has_lists(complex_docx, handler):
    model = handler.ingest(complex_docx)
    list_items = model.get_elements_by_type(ElementType.LIST_ITEM)
    assert len(list_items) >= 3


# ── Content hashes ────────────────────────────────────────────────────────────

def test_ingest_elements_have_content_hashes(simple_docx, handler):
    model = handler.ingest(simple_docx)
    for elem in model.elements:
        assert elem.content_hash != "", f"Element {elem.type} missing content hash"
        assert len(elem.content_hash) == 16


# ── Extract styles ────────────────────────────────────────────────────────────

def test_extract_styles_returns_dict(simple_docx, handler):
    styles = handler.extract_styles(simple_docx)
    assert isinstance(styles, dict)


def test_extract_styles_has_document_level(simple_docx, handler):
    styles = handler.extract_styles(simple_docx)
    assert "document_level" in styles


def test_extract_styles_document_level_has_margins(simple_docx, handler):
    styles = handler.extract_styles(simple_docx)
    dl = styles["document_level"]
    # At least some margin keys should be present
    margin_keys = [k for k in dl if "margin" in k]
    assert len(margin_keys) > 0


def test_extract_styles_per_element_keyed_by_hash(simple_docx, handler):
    from core.document_model import compute_content_hash
    styles = handler.extract_styles(simple_docx)
    # All non-special keys should look like content hashes (16 hex chars)
    special_keys = {"document_level", "schema_version"}
    for key in styles:
        if key in special_keys:
            continue
        assert len(key) == 16, f"Style key '{key}' is not a 16-char hash"


# ── Export (Tier 1) ───────────────────────────────────────────────────────────

def test_export_creates_docx(simple_docx, handler, tmp_path):
    model = handler.ingest(simple_docx)
    out = tmp_path / "output.docx"
    handler.export(model, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_roundtrip_headings(simple_docx, handler, tmp_path):
    """Export a model and re-ingest it — headings should survive."""
    model = handler.ingest(simple_docx)
    out = tmp_path / "roundtrip.docx"
    handler.export(model, out)

    model2 = handler.ingest(out)
    headings2 = model2.get_elements_by_type(ElementType.HEADING)
    assert len(headings2) >= 1


def test_export_roundtrip_table(simple_docx, handler, tmp_path):
    model = handler.ingest(simple_docx)
    out = tmp_path / "rt_table.docx"
    handler.export(model, out)

    model2 = handler.ingest(out)
    tables2 = model2.get_elements_by_type(ElementType.TABLE)
    assert len(tables2) >= 1


# ── Format handler interface ──────────────────────────────────────────────────

def test_supports_format():
    assert DocxHandler.supports_format("docx")
    assert DocxHandler.supports_format(".docx")
    assert DocxHandler.supports_format("DOCX")
    assert DocxHandler.supports_format("doc")
    assert not DocxHandler.supports_format("pdf")
    assert not DocxHandler.supports_format("md")


def test_extensions_list():
    assert "docx" in DocxHandler.EXTENSIONS
    assert "doc" in DocxHandler.EXTENSIONS


# ── Phase 5 edge cases ──────────────────────────────────────────────────────

def test_long_paragraph_no_truncation(tmp_path):
    """10,000+ char paragraph should not be truncated or crash."""
    import docx

    doc = docx.Document()
    long_text = "Lorem ipsum dolor sit amet. " * 500  # ~14,000 chars
    doc.add_paragraph(long_text)
    path = tmp_path / "long.docx"
    doc.save(str(path))

    handler = DocxHandler()
    model = handler.ingest(path)

    paras = model.get_elements_by_type(ElementType.PARAGRAPH)
    assert len(paras) >= 1
    assert len(str(paras[0].content)) > 10000


def test_export_all_three_tiers(simple_docx, tmp_path):
    """Explicit Tier 1/2/3 export using fixture + sidecar + original."""
    handler = DocxHandler()
    model = handler.ingest(simple_docx)
    styles = handler.extract_styles(simple_docx)

    # Tier 1 — no sidecar
    out1 = tmp_path / "tier1.docx"
    handler.export(model, out1)
    assert out1.exists()

    # Tier 2 — with sidecar
    out2 = tmp_path / "tier2.docx"
    handler.export(model, out2, sidecar=styles)
    assert out2.exists()

    # Tier 3 — with sidecar + original
    out3 = tmp_path / "tier3.docx"
    handler.export(model, out3, sidecar=styles, original_path=simple_docx)
    assert out3.exists()


def test_corrupt_docx_raises(tmp_path):
    """Corrupt DOCX should raise an error, not silently produce empty model."""
    bad = tmp_path / "corrupt.docx"
    bad.write_bytes(b"this is not a valid docx file")

    handler = DocxHandler()
    with pytest.raises(Exception):
        handler.ingest(bad)
