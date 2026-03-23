"""
PDF format handler — dual-engine extraction, OCR integration, and WeasyPrint export.

PdfHandler.ingest(file_path) → DocumentModel:
  PyMuPDF (primary) + pdfplumber fallback for complex tables.
  Multi-signal OCR detection per page; processes page-by-page for large files.

PdfHandler.extract_styles(file_path) → dict:
  Page size, margins, font info per text block, layout zones.

PdfHandler.export(model, output_path, sidecar=None):
  DocumentModel → styled HTML → PDF via WeasyPrint (primary) or fpdf2 (fallback).
"""
