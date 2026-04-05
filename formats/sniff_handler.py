"""
Sniff-based format handler — .tmp and other ambiguous extensions.

Ingest:
  Uses MIME detection to identify the actual file type, then delegates
  to the appropriate registered handler. If no handler matches, treats
  the file as plain text or reports binary metadata.

Export:
  Not supported — the original format is unknown.
"""

import time
from pathlib import Path
from typing import Any

import structlog

from formats.base import FormatHandler, register_handler, get_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)

log = structlog.get_logger(__name__)

# MIME type → handler extension mapping for delegation
_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.ms-powerpoint": "ppt",
    "application/rtf": "rtf",
    "text/html": "html",
    "text/xml": "xml",
    "application/xml": "xml",
    "application/json": "json",
    "text/csv": "csv",
    "text/plain": "txt",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/tiff": "tiff",
    "image/svg+xml": "svg",
    "application/zip": "zip",
    "application/x-7z-compressed": "7z",
    "application/x-rar-compressed": "rar",
    "application/epub+zip": "epub",
}


@register_handler
class SniffHandler(FormatHandler):
    """Sniff-based handler for ambiguous file extensions like .tmp."""

    EXTENSIONS = ["tmp"]

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="sniff")

        # Step 1: Try MIME detection
        detected_ext = self._detect_type(file_path)

        if detected_ext:
            handler = get_handler(detected_ext)
            if handler:
                log.info("sniff_delegated", filename=file_path.name,
                         detected_ext=detected_ext, handler=type(handler).__name__)
                return handler.ingest(file_path)

        # Step 2: Try reading as text
        try:
            raw = file_path.read_bytes()
            # Check if mostly printable ASCII/UTF-8
            try:
                text = raw.decode("utf-8")
                non_printable = sum(1 for c in text[:1000] if not c.isprintable() and c not in "\n\r\t")
                if non_printable < len(text[:1000]) * 0.1:  # <10% non-printable = likely text
                    log.info("sniff_as_text", filename=file_path.name)
                    from formats.txt_handler import TxtHandler
                    return TxtHandler().ingest(file_path)
            except UnicodeDecodeError:
                pass
        except OSError:
            pass

        # Step 3: Fall back to metadata-only
        return self._metadata_only(file_path, t_start)

    def _detect_type(self, file_path: Path) -> str | None:
        """Use python-magic to detect MIME type and map to a handler extension."""
        try:
            import magic
            mime = magic.from_file(str(file_path), mime=True)
            if mime and mime != "application/octet-stream":
                ext = _MIME_TO_EXT.get(mime)
                if ext:
                    return ext
                log.debug("sniff_unknown_mime", filename=file_path.name, mime=mime)
        except Exception as exc:
            log.debug("sniff_magic_failed", filename=file_path.name, error=str(exc))
        return None

    def _metadata_only(self, file_path: Path, t_start: float) -> DocumentModel:
        """Produce a minimal DocumentModel with file metadata."""
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="tmp",
        )

        stat = file_path.stat()
        size_h = f"{stat.st_size / 1024:.1f} KB" if stat.st_size < 1048576 else f"{stat.st_size / 1048576:.1f} MB"

        # Read magic bytes
        try:
            header = file_path.read_bytes()[:16]
            hex_header = " ".join(f"{b:02x}" for b in header)
        except OSError:
            hex_header = "(unreadable)"

        model.add_element(Element(type=ElementType.HEADING, content=file_path.name, level=1))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content=f"**Type:** Temporary file (content type unknown)\n"
                    f"**Size:** {size_h}\n"
                    f"**Header bytes:** `{hex_header}`",
        ))

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms, sniff_result="metadata_only")
        return model

    def export(self, model: DocumentModel, output_path: Path,
               sidecar: dict[str, Any] | None = None, original_path: Path | None = None) -> None:
        raise NotImplementedError("Cannot export .tmp files — original format unknown")

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
