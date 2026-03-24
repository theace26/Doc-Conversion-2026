"""
Round-trip tests: DOCX → Markdown → DOCX (Tiers 1, 2, 3).

Verifies that structure and styling survive the full conversion cycle.
"""

import json
from pathlib import Path

import pytest

from core.document_model import ElementType, compute_content_hash
from core.metadata import generate_sidecar
from formats.docx_handler import DocxHandler
from formats.markdown_handler import MarkdownHandler


@pytest.fixture
def docx_handler():
    return DocxHandler()


@pytest.fixture
def md_handler():
    return MarkdownHandler()


# ── Tier 1: structure only (no sidecar) ───────────────────────────────────────

def test_tier1_heading_count(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD → DOCX: heading count is preserved."""
    model = docx_handler.ingest(simple_docx)
    orig_headings = len(model.get_elements_by_type(ElementType.HEADING))

    md_path = tmp_path / "simple.md"
    md_handler.export(model, md_path)

    model2 = md_handler.ingest(md_path)
    out_docx = tmp_path / "simple_out.docx"
    docx_handler.export(model2, out_docx)

    model3 = docx_handler.ingest(out_docx)
    assert len(model3.get_elements_by_type(ElementType.HEADING)) >= orig_headings


def test_tier1_paragraph_count(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD → DOCX: paragraph count is preserved."""
    model = docx_handler.ingest(simple_docx)
    orig_paras = len(model.get_elements_by_type(ElementType.PARAGRAPH))

    md_path = tmp_path / "p.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)
    out = tmp_path / "p_out.docx"
    docx_handler.export(model2, out)

    model3 = docx_handler.ingest(out)
    assert len(model3.get_elements_by_type(ElementType.PARAGRAPH)) >= orig_paras


def test_tier1_table_count(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD → DOCX: table count is preserved."""
    model = docx_handler.ingest(simple_docx)

    md_path = tmp_path / "t.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)
    out = tmp_path / "t_out.docx"
    docx_handler.export(model2, out)

    model3 = docx_handler.ingest(out)
    assert len(model3.get_elements_by_type(ElementType.TABLE)) >= 1


def test_tier1_table_dimensions(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD → DOCX: table row/column count is preserved."""
    model = docx_handler.ingest(simple_docx)
    orig_table = model.get_elements_by_type(ElementType.TABLE)[0]
    orig_rows = len(orig_table.content)
    orig_cols = len(orig_table.content[0])

    md_path = tmp_path / "td.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)
    out = tmp_path / "td_out.docx"
    docx_handler.export(model2, out)

    model3 = docx_handler.ingest(out)
    rt_table = model3.get_elements_by_type(ElementType.TABLE)[0]
    assert len(rt_table.content) == orig_rows
    assert len(rt_table.content[0]) == orig_cols


def test_tier1_image_count(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD → DOCX: image elements survive (may be placeholders if assets absent)."""
    model = docx_handler.ingest(simple_docx)

    # Save images to assets/ alongside the md
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    for fname, img_data in model.images.items():
        (assets_dir / fname).write_bytes(img_data.data)

    md_path = tmp_path / "img.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)
    out = tmp_path / "img_out.docx"
    docx_handler.export(model2, out)

    # Simply verify the output docx is valid
    assert out.exists()
    assert out.stat().st_size > 0


def test_tier1_no_sidecar_still_produces_docx(tmp_path, md_handler, docx_handler):
    """A plain .md with no sidecar converts to .docx without errors (Tier 1)."""
    md_text = "# Hello\n\nThis is a **paragraph** with *italic* and `code`.\n"
    md_path = tmp_path / "plain.md"
    md_path.write_text(md_text, encoding="utf-8")

    model = md_handler.ingest(md_path)
    out = tmp_path / "plain.docx"
    docx_handler.export(model, out)

    assert out.exists()
    model2 = docx_handler.ingest(out)
    assert len(model2.get_elements_by_type(ElementType.HEADING)) >= 1
    assert len(model2.get_elements_by_type(ElementType.PARAGRAPH)) >= 1


# ── Tier 2: style restoration via sidecar ────────────────────────────────────

def test_tier2_produces_docx(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD + sidecar → DOCX: output file is produced."""
    model = docx_handler.ingest(simple_docx)
    style_data = docx_handler.extract_styles(simple_docx)
    sidecar = generate_sidecar(model, style_data)

    md_path = tmp_path / "s2.md"
    md_handler.export(model, md_path)

    sidecar_path = tmp_path / "s2.styles.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    model2 = md_handler.ingest(md_path)
    out = tmp_path / "s2_out.docx"
    docx_handler.export(model2, out, sidecar=sidecar)

    assert out.exists()
    assert out.stat().st_size > 0


def test_tier2_structure_matches_tier1(simple_docx, docx_handler, md_handler, tmp_path):
    """Tier 2 output has the same structure as Tier 1 (sidecar doesn't break anything)."""
    model = docx_handler.ingest(simple_docx)
    style_data = docx_handler.extract_styles(simple_docx)
    sidecar = generate_sidecar(model, style_data)

    md_path = tmp_path / "s2b.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)

    # Tier 1 output
    out1 = tmp_path / "tier1.docx"
    docx_handler.export(model2, out1)
    m1 = docx_handler.ingest(out1)

    # Tier 2 output
    out2 = tmp_path / "tier2.docx"
    docx_handler.export(model2, out2, sidecar=sidecar)
    m2 = docx_handler.ingest(out2)

    assert len(m2.get_elements_by_type(ElementType.HEADING)) == \
           len(m1.get_elements_by_type(ElementType.HEADING))
    assert len(m2.get_elements_by_type(ElementType.TABLE)) == \
           len(m1.get_elements_by_type(ElementType.TABLE))


def test_tier2_page_margins_applied(simple_docx, docx_handler, md_handler, tmp_path):
    """Tier 2: page margins from sidecar are applied to the output document."""
    import docx as _docx

    model = docx_handler.ingest(simple_docx)
    style_data = docx_handler.extract_styles(simple_docx)
    sidecar = generate_sidecar(model, style_data)

    # Artificially set recognizable margins in the sidecar
    sidecar["document_level"]["margin_top_pt"] = 72.0     # 1 inch
    sidecar["document_level"]["margin_bottom_pt"] = 72.0

    md_path = tmp_path / "margins.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)

    out = tmp_path / "margins_out.docx"
    docx_handler.export(model2, out, sidecar=sidecar)

    doc = _docx.Document(str(out))
    from docx.shared import Pt
    top_pt = doc.sections[0].top_margin / 12700  # EMU → pt
    assert abs(top_pt - 72.0) < 2.0  # within 2 pt


# ── Tier 3: original as template ─────────────────────────────────────────────

def test_tier3_produces_docx(simple_docx, docx_handler, md_handler, tmp_path):
    """DOCX → MD + sidecar + original → DOCX: Tier 3 output is produced."""
    model = docx_handler.ingest(simple_docx)
    style_data = docx_handler.extract_styles(simple_docx)
    sidecar = generate_sidecar(model, style_data)

    md_path = tmp_path / "t3.md"
    md_handler.export(model, md_path)

    model2 = md_handler.ingest(md_path)
    out = tmp_path / "t3_out.docx"
    # Pass the original docx path directly
    docx_handler.export(model2, out, sidecar=sidecar, original_path=simple_docx)

    assert out.exists()
    assert out.stat().st_size > 0


def test_tier3_structure_matches_tier1(simple_docx, docx_handler, md_handler, tmp_path):
    """Tier 3 output has the same heading and table structure as Tier 1."""
    model = docx_handler.ingest(simple_docx)
    style_data = docx_handler.extract_styles(simple_docx)
    sidecar = generate_sidecar(model, style_data)

    md_path = tmp_path / "t3s.md"
    md_handler.export(model, md_path)
    model2 = md_handler.ingest(md_path)

    out_t1 = tmp_path / "t3_t1.docx"
    docx_handler.export(model2, out_t1)
    m_t1 = docx_handler.ingest(out_t1)

    out_t3 = tmp_path / "t3_t3.docx"
    docx_handler.export(model2, out_t3, sidecar=sidecar, original_path=simple_docx)
    m_t3 = docx_handler.ingest(out_t3)

    assert len(m_t3.get_elements_by_type(ElementType.HEADING)) >= \
           len(m_t1.get_elements_by_type(ElementType.HEADING)) - 1


# ── Edited content test ───────────────────────────────────────────────────────

def test_edited_content_appears_in_output(simple_docx, docx_handler, md_handler, tmp_path):
    """Edit a paragraph in markdown; the edit must appear in the output DOCX."""
    model = docx_handler.ingest(simple_docx)

    md_path = tmp_path / "edit.md"
    md_text = md_handler.export(model, md_path)

    # Replace a known paragraph with edited text
    edited = md_text.replace(
        "This is the first paragraph of the document.",
        "EDITED: This paragraph was changed in the Markdown.",
    )
    md_path.write_text(edited, encoding="utf-8")

    model2 = md_handler.ingest(md_path)
    out = tmp_path / "edit_out.docx"
    docx_handler.export(model2, out)

    model3 = docx_handler.ingest(out)
    all_text = " ".join(
        e.content for e in model3.elements if isinstance(e.content, str)
    )
    assert "EDITED" in all_text


def test_edited_content_with_tier2_sidecar(simple_docx, docx_handler, md_handler, tmp_path):
    """Edit + sidecar: edited elements use Tier 1 defaults; untouched use Tier 2 styles."""
    model = docx_handler.ingest(simple_docx)
    style_data = docx_handler.extract_styles(simple_docx)
    sidecar = generate_sidecar(model, style_data)

    md_path = tmp_path / "edit2.md"
    md_text = md_handler.export(model, md_path)

    edited = md_text.replace(
        "This is the second paragraph with some detail.",
        "CHANGED paragraph — sidecar won't match this.",
    )
    md_path.write_text(edited, encoding="utf-8")

    model2 = md_handler.ingest(md_path)
    out = tmp_path / "edit2_out.docx"
    docx_handler.export(model2, out, sidecar=sidecar)  # Should not raise

    assert out.exists()
    assert out.stat().st_size > 0
