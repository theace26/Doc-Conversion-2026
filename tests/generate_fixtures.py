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

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def generate_all() -> None:
    """Generate all test fixtures. Safe to call multiple times (idempotent)."""
    FIXTURES_DIR.mkdir(exist_ok=True)
    # Fixture generation implemented in Phase 1+


if __name__ == "__main__":
    generate_all()
    print(f"Fixtures generated in {FIXTURES_DIR}")
