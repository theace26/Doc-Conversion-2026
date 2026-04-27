"""
Sniff-based format handler — .tmp / .tmk and browser-download suffixes.

Ingest:
  Uses a layered detection strategy to identify the actual file type,
  then delegates to the appropriate registered handler:

  1. **Browser-suffix strip** (v0.32.2). For files with a
     `.download`, `.crdownload`, `.part`, or `.partial` suffix, strip
     the trailing token and check whether the inner extension has a
     registered handler. Recovers a Chrome / Edge / Firefox / Safari
     "Save Page As — Complete" `.js.download` (real type: JavaScript)
     or a Chrome `.pdf.crdownload` interrupted-download
     (real type: PDF) without paying for content sniffing.
  2. **MIME-byte detection** via `python-magic` (libmagic). Catches
     content-vs-extension mismatches even after the inner extension
     check failed (e.g., a `.dat` file that's actually a JPEG).
  3. **UTF-8 text fallback**. If the file is mostly printable text,
     route through TxtHandler so JS / CSS / log content is at least
     indexed even when no specific format handler matches.
  4. **Metadata-only stub**. Last-resort defensive output: filename,
     size, hex of the first 16 bytes — at least the file shows up
     as `converted` rather than `unrecognized`.

  Plan: docs/superpowers/plans/2026-04-27-unrecognized-file-recovery.md

Export:
  Not supported — the original format is unknown / synthesized.
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

# v0.32.2: browser-download suffixes. Modern browsers append these
# during in-flight downloads (`.crdownload` for Chrome/Edge,
# `.part` / `.partial` for Firefox/Safari) AND for Save-Page-As-
# Complete files (`.download` for Safari). Strip them and check
# the inner extension before falling back to content sniffing.
_BROWSER_DOWNLOAD_SUFFIXES = (
    ".download",
    ".crdownload",
    ".part",
    ".partial",
)


def _strip_browser_suffix(file_path: Path) -> str | None:
    """If `file_path.name` ends with a browser-download suffix,
    return the inner-extension stem (e.g. ".js" for
    "add-to-cart.min.js.download"). Returns None if no suffix
    matched OR the stripped name has no extension.
    """
    name_lower = file_path.name.lower()
    for sfx in _BROWSER_DOWNLOAD_SUFFIXES:
        if name_lower.endswith(sfx):
            stripped_name = file_path.name[: -len(sfx)]
            stripped_path = Path(stripped_name)
            inner_ext = stripped_path.suffix.lower()
            if inner_ext:
                return inner_ext
            return None
    return None


@register_handler
class SniffHandler(FormatHandler):
    """Sniff-based handler for ambiguous / recovered extensions.

    Registered for:
      - `.tmp` — generic temp files (original purpose)
      - `.tmk` — small marker files seen alongside MP3 recordings
        in audio-transcribe folders. Real format unknown; sniff +
        delegate, fall back to metadata-only stub. (v0.32.2; plan
        Phase 1c)
      - `.download` / `.crdownload` / `.part` / `.partial` — browser
        in-flight or save-page-as suffixes. Strip the suffix and
        delegate to the handler for the inner extension. (v0.32.2;
        plan Phase 3)
    """

    EXTENSIONS = ["tmp", "tmk", "download", "crdownload", "part", "partial"]

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="sniff")

        # Step 0 (v0.32.2): browser-suffix shim. If the file is
        # `*.js.download` or similar, strip the suffix and look up
        # the inner extension's handler directly. Cheaper than
        # MIME-detecting and more accurate when the original
        # extension was correct.
        inner_ext = _strip_browser_suffix(file_path)
        if inner_ext:
            inner_handler = get_handler(inner_ext)
            if inner_handler:
                log.info(
                    "sniff_browser_suffix_recovered",
                    filename=file_path.name,
                    inner_ext=inner_ext,
                    handler=type(inner_handler).__name__,
                )
                return inner_handler.ingest(file_path)
            else:
                log.info(
                    "sniff_browser_suffix_no_handler",
                    filename=file_path.name,
                    inner_ext=inner_ext,
                )

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
        """Produce a minimal DocumentModel with file metadata.

        Last-resort output for files where every detection layer
        failed. Records what's recoverable (size + first 16 bytes
        as hex) and the originating extension so the operator can
        triage from the converted output rather than the
        unrecognized bucket.
        """
        # v0.32.2: source_format reflects the actual originating
        # extension (e.g. "tmk", "download") rather than always
        # "tmp" — tells the operator what they're looking at.
        ext = file_path.suffix.lower().lstrip(".") or "unknown"
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext,
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
            content=f"**Type:** Recovered file (content type unknown after sniffing)\n"
                    f"**Original extension:** `.{ext}`\n"
                    f"**Size:** {size_h}\n"
                    f"**Header bytes:** `{hex_header}`",
        ))

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms, sniff_result="metadata_only")
        return model

    def export(self, model: DocumentModel, output_path: Path,
               sidecar: dict[str, Any] | None = None, original_path: Path | None = None) -> None:
        raise NotImplementedError(
            "Cannot export sniffed files — original format unknown"
        )

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
