"""
Shortcut format handler — Windows .lnk and .url files.

Ingest:
  .url files: parsed as INI-like text to extract the target URL.
  .lnk files: binary Windows shortcuts; scans for readable path strings.

Export:
  Not supported — raises NotImplementedError.
"""

import configparser
import re
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

# Regex to find Windows-style paths in binary content
_PATH_RE = re.compile(
    rb"([A-Za-z]:\\[\\a-zA-Z0-9 _.\-]+)"   # e.g. C:\Users\foo\bar.exe
    rb"|"
    rb"(\\\\[a-zA-Z0-9_.\-]+\\[\\a-zA-Z0-9 _.\-]+)"  # e.g. \\server\share\path
)

_LNK_MAGIC = b"\x4c\x00\x00\x00"


@register_handler
class ShortcutHandler(FormatHandler):
    """Handler for Windows shortcut (.lnk) and URL shortcut (.url) files."""

    EXTENSIONS = ["lnk", "url"]

    # ── Ingest ────────────────────────────────────────────────────────────────

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

        if ext == "url":
            self._ingest_url(file_path, model)
        else:
            self._ingest_lnk(file_path, model)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
        )
        return model

    def _ingest_url(self, file_path: Path, model: DocumentModel) -> None:
        """Parse a .url (INI-like) shortcut file."""
        text = file_path.read_text(encoding="utf-8", errors="replace")

        target = None
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(text)
            target = parser.get("InternetShortcut", "URL", fallback=None)
        except (configparser.Error, KeyError):
            # Fallback: regex
            m = re.search(r"(?i)^URL\s*=\s*(.+)$", text, re.MULTILINE)
            if m:
                target = m.group(1).strip()

        model.add_element(Element(
            type=ElementType.HEADING,
            content=file_path.name,
            level=1,
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="Type: URL Shortcut",
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content=f"Target: {target}" if target else "Target: (unknown)",
        ))
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=text.rstrip(),
            attributes={"language": "ini"},
        ))

    def _ingest_lnk(self, file_path: Path, model: DocumentModel) -> None:
        """Parse a .lnk binary shortcut file."""
        raw = file_path.read_bytes()

        target = None
        if raw[:4] == _LNK_MAGIC:
            # Search for readable path strings in the binary content
            matches = _PATH_RE.findall(raw)
            for local_path, unc_path in matches:
                found = local_path or unc_path
                try:
                    decoded = found.decode("utf-8", errors="replace").strip()
                    if decoded:
                        target = decoded
                        break
                except Exception:
                    continue

        model.add_element(Element(
            type=ElementType.HEADING,
            content=file_path.name,
            level=1,
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="Type: Windows Shortcut",
        ))

        if target:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content=f"Target: {target}",
            ))
        else:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="Target: Windows shortcut (binary, target unknown)",
            ))

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        raise NotImplementedError("Export is not supported for shortcut files.")

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
