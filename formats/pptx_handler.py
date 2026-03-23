"""
PPTX format handler — slide extraction and reconstruction via python-pptx.

PptxHandler.ingest(file_path) → DocumentModel:
  Each slide → H2 section. Titles, body, tables, images, speaker notes.
  Charts/SmartArt → image via LibreOffice headless, warning added to model.

PptxHandler.extract_styles(file_path) → dict:
  Slide dimensions, placeholder positions, theme colors, font schemes.

PptxHandler.export(model, output_path, sidecar=None):
  Rebuilds PPTX from H2-delimited sections. Restores layout + notes from sidecar/original.
"""
