"""
Binary/opaque file metadata handler — .bin, .cl4 and other binary formats.

Ingest:
  Records file size, MIME type, and magic header bytes. These files cannot
  be meaningfully converted to Markdown, but cataloguing them removes them
  from the "unrecognized" count and makes them searchable by filename.

Export:
  Not supported — binary reconstruction not possible.
"""

import time
from pathlib import Path
from typing import Any

import structlog

from formats.base import FormatHandler, register_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)

log = structlog.get_logger(__name__)


@register_handler
class BinaryHandler(FormatHandler):
    """Metadata-only handler for opaque binary files."""

    EXTENSIONS = ["bin", "cl4"]

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        ext = file_path.suffix.lower().lstrip(".")
        log.info("handler_ingest_start", filename=file_path.name, format=ext)

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext,
        )

        stat = file_path.stat()
        size_h = f"{stat.st_size / 1024:.1f} KB" if stat.st_size < 1048576 else f"{stat.st_size / 1048576:.1f} MB"

        # MIME detection
        mime = "application/octet-stream"
        try:
            import magic
            mime = magic.from_file(str(file_path), mime=True) or mime
        except Exception:
            pass

        # Read magic bytes
        try:
            header = file_path.read_bytes()[:16]
            hex_header = " ".join(f"{b:02x}" for b in header)
        except OSError:
            hex_header = "(unreadable)"

        # File type descriptions
        type_desc = {
            "bin": "Binary data file",
            "cl4": "Easy CD Creator 4 project file",
        }.get(ext, "Binary file")

        model.add_element(Element(type=ElementType.HEADING, content=file_path.name, level=1))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content=f"**Type:** {type_desc}\n"
                    f"**Size:** {size_h}\n"
                    f"**MIME:** `{mime}`\n"
                    f"**Header bytes:** `{hex_header}`",
        ))

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def export(self, model: DocumentModel, output_path: Path,
               sidecar: dict[str, Any] | None = None, original_path: Path | None = None) -> None:
        raise NotImplementedError("Binary files cannot be reconstructed from text")

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
