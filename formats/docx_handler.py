"""
DOCX/DOC format handler — bidirectional conversion via python-docx.

DocxHandler.ingest(file_path) → DocumentModel:
  Extracts headings, paragraphs, tables (nested), inline images, footnotes.
  .doc files are first converted to .docx via LibreOffice headless.

DocxHandler.extract_styles(file_path) → dict:
  Per-element font/size/spacing/color, table structure, document-level page settings.

DocxHandler.export(model, output_path, sidecar=None):
  Tier 1: structure always. Tier 2: styles from sidecar. Tier 3: patch against original.
"""
