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
# v0.34.0: dedicated deep handler for Premiere Pro projects. Imported AFTER
# adobe_handler so its `prproj` registration wins routing (registry is
# last-writer-wins). adobe_handler.EXTENSIONS also drops `prproj` for clarity.
from formats.prproj.handler import PrprojHandler  # noqa: F401
from formats.json_handler import JsonHandler  # noqa: F401
from formats.yaml_handler import YamlHandler  # noqa: F401
from formats.ini_handler import IniHandler  # noqa: F401
from formats.archive_handler import ArchiveHandler  # noqa: F401
from formats.audio_handler import AudioHandler  # noqa: F401
from formats.media_handler import MediaHandler  # noqa: F401
from formats.image_handler import ImageHandler  # noqa: F401
from formats.font_handler import FontHandler  # noqa: F401
from formats.shortcut_handler import ShortcutHandler  # noqa: F401
from formats.vcf_handler import VcfHandler  # noqa: F401
from formats.svg_handler import SvgHandler  # noqa: F401
from formats.sniff_handler import SniffHandler  # noqa: F401
from formats.binary_handler import BinaryHandler  # noqa: F401
from formats.database_handler import DatabaseHandler  # noqa: F401
