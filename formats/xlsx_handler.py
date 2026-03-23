"""
XLSX/CSV format handler — spreadsheet extraction and reconstruction via openpyxl/pandas.

XlsxHandler.ingest(file_path) → DocumentModel:
  Each sheet → H2 section + TABLE element.
  Formulas preserved as <!-- FORMULA: =expr --> annotations.
  CSV treated as single-sheet workbook via pandas.

XlsxHandler.extract_styles(file_path) → dict:
  Column widths, row heights, number formats, merged cells, sheet names.

XlsxHandler.export(model, output_path, sidecar=None):
  Rebuilds workbook; restores column widths, formulas, merged cells from sidecar.
"""
