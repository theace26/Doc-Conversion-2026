"""
Format handler package — one handler per supported document format.

All handlers extend FormatHandler (formats/base.py) and register themselves
via a class registry so the converter can look up the correct handler by extension.
"""

# Import all handlers so they register themselves in the format registry.
# This must happen before any call to get_handler() / get_handler_for_path().
from formats.docx_handler import DocxHandler  # noqa: F401
from formats.markdown_handler import MarkdownHandler  # noqa: F401
from formats.pdf_handler import PdfHandler  # noqa: F401
from formats.pptx_handler import PptxHandler  # noqa: F401
from formats.xlsx_handler import XlsxHandler  # noqa: F401
from formats.csv_handler import CsvHandler  # noqa: F401
