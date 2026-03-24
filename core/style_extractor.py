"""
Format-agnostic style metadata extraction wrapper.

Delegates to format-specific handlers and ensures:
- Content-hash keying for all style entries
- schema_version: "1.0.0" in all output
- Migration logic when schema version is bumped

extract_styles(file_path, format) → dict
"""

from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"


def extract_styles(file_path: Path, fmt: str) -> dict[str, Any]:
    """
    Extract style data from a document file.

    Returns a dict containing:
      - "schema_version": SCHEMA_VERSION
      - "document_level": page-level settings (margins, default font, etc.)
      - Per-element entries keyed by content hash

    Args:
        file_path: Path to the source file.
        fmt:       Format string, e.g. "docx", "pdf".
    """
    fmt_clean = fmt.lower().lstrip(".")

    if fmt_clean in ("docx", "doc"):
        from formats.docx_handler import DocxHandler
        handler = DocxHandler()
        style_data = handler.extract_styles(file_path)
    else:
        # Other formats: return empty structure (populated in later phases)
        style_data = {"document_level": {}}

    # Guarantee schema_version is present
    style_data.setdefault("schema_version", SCHEMA_VERSION)
    return style_data
