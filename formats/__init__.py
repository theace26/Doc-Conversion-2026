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
from formats.rtf_handler import RtfHandler  # noqa: F401
from formats.txt_handler import TxtHandler  # noqa: F401
from formats.html_handler import HtmlHandler  # noqa: F401
from formats.odt_handler import OdtHandler  # noqa: F401
from formats.ods_handler import OdsHandler  # noqa: F401
from formats.odp_handler import OdpHandler  # noqa: F401
from formats.epub_handler import EpubHandler  # noqa: F401
from formats.eml_handler import EmlHandler  # noqa: F401
from formats.xml_handler import XmlHandler  # noqa: F401
from formats.adobe_handler import AdobeHandler  # noqa: F401
