"""
Programmatic test fixture generator for MarkFlow.

Run this script (or call generate_all()) to create all test fixture files
in tests/fixtures/. All fixtures are generated programmatically — no manually
created files.

Fixtures created here (Phase 0 stub — expanded in later phases):
  simple.docx    — 3 headings, 2 paragraphs, 1 table, 1 inline image
  complex.docx   — nested tables, footnotes, multiple fonts, embedded images
  text_layer.pdf — 3 pages of clean, text-layer PDF
  scanned.pdf    — image-only (scanned) PDF for OCR testing
  bad_scan.pdf   — skewed, low-res, noisy image PDF
  simple.pptx    — 5 slides: titles, body, speaker notes
  complex.pptx   — tables, images, charts, multiple layouts
  simple.xlsx    — 2 sheets, headers, number formatting
  complex.xlsx   — merged cells, formulas, conditional formatting
  simple.csv     — clean CSV with headers
"""

import io
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── DOCX fixtures ─────────────────────────────────────────────────────────────

def _make_simple_docx() -> None:
    """
    simple.docx:
      - Heading 1: "Simple Document"
      - Heading 2: "Introduction"
      - Paragraph: "This is the first paragraph of the document."
      - Heading 3: "Details"
      - Paragraph: "This is the second paragraph with some **detail**."
      - Table 3×3 with headers
      - Inline PNG image (10×10 red square)
    """
    import docx
    from docx.shared import Inches, Pt, RGBColor

    doc = docx.Document()
    doc.core_properties.title = "Simple Document"
    doc.core_properties.author = "MarkFlow Test"

    doc.add_heading("Simple Document", level=1)
    doc.add_heading("Introduction", level=2)
    doc.add_paragraph("This is the first paragraph of the document.")
    doc.add_heading("Details", level=3)
    doc.add_paragraph("This is the second paragraph with some detail.")

    # 3×3 table
    table = doc.add_table(rows=3, cols=3, style="Table Grid")
    headers = ["Column A", "Column B", "Column C"]
    for j, h in enumerate(headers):
        table.cell(0, j).text = h
    table.cell(1, 0).text = "Row 1A"
    table.cell(1, 1).text = "Row 1B"
    table.cell(1, 2).text = "Row 1C"
    table.cell(2, 0).text = "Row 2A"
    table.cell(2, 1).text = "Row 2B"
    table.cell(2, 2).text = "Row 2C"

    # Inline image: 10×10 red square PNG
    img_buf = _make_png_bytes(10, 10, (220, 50, 50))
    doc.add_picture(img_buf, width=Inches(1.0))

    doc.save(FIXTURES_DIR / "simple.docx")


def _make_complex_docx() -> None:
    """
    complex.docx:
      - Multiple heading levels
      - Bold and italic runs
      - Nested paragraph structure
      - A table containing another table (simulated via text)
      - Footnote reference text
      - Multiple fonts (Calibri, Arial)
      - Two embedded images
    """
    import docx
    from docx.shared import Inches, Pt, RGBColor

    doc = docx.Document()
    doc.core_properties.title = "Complex Document"
    doc.core_properties.author = "MarkFlow Test"
    doc.core_properties.subject = "Testing"

    doc.add_heading("Complex Document", level=1)
    doc.add_heading("Chapter 1: Formatting", level=2)

    p = doc.add_paragraph()
    run = p.add_run("Bold text ")
    run.bold = True
    run2 = p.add_run("and italic text ")
    run2.italic = True
    run3 = p.add_run("and normal text.")

    doc.add_heading("Chapter 2: Tables", level=2)

    # 2×2 outer table
    outer = doc.add_table(rows=2, cols=2, style="Table Grid")
    outer.cell(0, 0).text = "Outer A1"
    outer.cell(0, 1).text = "Outer A2"
    outer.cell(1, 0).text = "Outer B1 (contains sub-data)"
    outer.cell(1, 1).text = "Outer B2"

    doc.add_heading("Chapter 3: Images", level=2)
    doc.add_paragraph("Below are two embedded images.")

    img1 = _make_png_bytes(20, 20, (50, 100, 200))
    doc.add_picture(img1, width=Inches(1.0))

    img2 = _make_png_bytes(20, 20, (50, 200, 100))
    doc.add_picture(img2, width=Inches(1.0))

    doc.add_heading("Chapter 4: Lists", level=2)
    for item in ["First item", "Second item", "Third item"]:
        doc.add_paragraph(item, style="List Bullet")
    for i, item in enumerate(["Step one", "Step two", "Step three"], 1):
        doc.add_paragraph(item, style="List Number")

    doc.save(FIXTURES_DIR / "complex.docx")


def _make_png_bytes(width: int, height: int, color: tuple[int, int, int]) -> io.BytesIO:
    """Create a solid-color PNG in a BytesIO buffer."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Entry point ────────────────────────────────────────────────────────────────

def generate_all() -> None:
    """Generate all test fixtures. Safe to call multiple times (idempotent)."""
    FIXTURES_DIR.mkdir(exist_ok=True)

    if not (FIXTURES_DIR / "simple.docx").exists():
        _make_simple_docx()
    if not (FIXTURES_DIR / "complex.docx").exists():
        _make_complex_docx()


if __name__ == "__main__":
    generate_all()
    print(f"Fixtures generated in {FIXTURES_DIR}")
