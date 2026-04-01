"""
Adobe format handler — PSD, AI, INDD, AEP, PRPROJ, XD files.

Ingest:
  Extracts text layers and metadata using psd-tools (PSD), pdfplumber (AI),
  and exiftool (all types). Converts extracted content into DocumentModel
  paragraphs so Adobe files can be searched and converted like any other.

Export:
  Not supported — Adobe formats require proprietary tools to author.
  Export writes a Markdown summary of extracted content instead.
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
class AdobeHandler(FormatHandler):
    """Handler for Adobe creative suite files: PSD, AI, INDD, AEP, PRPROJ, XD."""

    EXTENSIONS = ["psd", "ai", "indd", "aep", "prproj", "xd", "ait", "indt"]

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

        # Extract metadata via exiftool
        metadata = self._extract_metadata(file_path)
        if metadata:
            model.style_data["adobe_metadata"] = metadata
            # Pull common metadata fields
            model.metadata.title = metadata.get("Title", metadata.get("DocumentTitle", ""))
            model.metadata.author = metadata.get("Creator", metadata.get("Author", ""))

        # File info heading
        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"{file_path.name}",
            level=1,
        ))

        # Metadata summary
        if metadata:
            meta_lines = []
            for key in ("FileType", "Creator", "Producer", "CreateDate", "ModifyDate",
                        "ImageWidth", "ImageHeight", "ColorMode", "BitDepth",
                        "Duration", "FrameRate", "PageCount"):
                if key in metadata:
                    meta_lines.append(f"{key}: {metadata[key]}")
            if meta_lines:
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content="\n".join(meta_lines),
                    attributes={"role": "metadata_summary"},
                ))

        # Extract text content based on format
        if ext == "psd":
            text_layers = self._extract_psd_text(file_path)
            if text_layers:
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content="Text Layers",
                    level=2,
                ))
                for layer_name, layer_text in text_layers:
                    content = f"{layer_name}: {layer_text}" if layer_name else layer_text
                    model.add_element(Element(
                        type=ElementType.PARAGRAPH,
                        content=content,
                    ))
                model.style_data["text_layers"] = [
                    {"name": n, "text": t} for n, t in text_layers
                ]

        elif ext == "ai":
            text_content = self._extract_ai_text(file_path)
            if text_content:
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content="Document Text",
                    level=2,
                ))
                for para in text_content.split("\n\n"):
                    para = para.strip()
                    if para:
                        model.add_element(Element(
                            type=ElementType.PARAGRAPH,
                            content=para,
                        ))

        # For INDD, AEP, PRPROJ, XD — metadata only (no text extraction available
        # without proprietary SDKs)
        if ext in ("indd", "aep", "prproj", "xd") and not any(
            e.type == ElementType.PARAGRAPH for e in model.elements
        ):
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content=f"Adobe {ext.upper()} file — metadata extracted, content requires {self._tool_name(ext)}.",
            ))

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _extract_metadata(self, file_path: Path) -> dict[str, str]:
        """Extract metadata via exiftool."""
        try:
            import subprocess
            import json

            result = subprocess.run(
                ["exiftool", "-json", "-n", str(file_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data and isinstance(data, list):
                    meta = data[0]
                    # Clean up: remove binary fields and overly long values
                    cleaned = {}
                    for k, v in meta.items():
                        if isinstance(v, str) and len(v) > 2000:
                            continue
                        if isinstance(v, (bytes, bytearray)):
                            continue
                        if k.startswith("ExifTool") or k == "SourceFile":
                            continue
                        cleaned[k] = str(v) if v is not None else ""
                    return cleaned
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as exc:
            log.debug("adobe_exiftool_failed", file=file_path.name, error=str(exc))
        return {}

    def _extract_psd_text(self, file_path: Path) -> list[tuple[str, str]]:
        """Extract text layers from PSD file."""
        layers: list[tuple[str, str]] = []
        try:
            from psd_tools import PSDImage
            psd = PSDImage.open(str(file_path))
            self._walk_psd_layers(psd, layers)
        except Exception as exc:
            log.debug("adobe_psd_text_failed", file=file_path.name, error=str(exc))
        return layers

    def _walk_psd_layers(self, group, layers: list[tuple[str, str]]) -> None:
        """Recursively walk PSD layers looking for text."""
        for layer in group:
            if layer.kind == "type" and hasattr(layer, "text"):
                text = layer.text.strip() if layer.text else ""
                if text:
                    layers.append((layer.name, text))
            if hasattr(layer, "__iter__"):
                try:
                    self._walk_psd_layers(layer, layers)
                except Exception:
                    pass

    def _extract_ai_text(self, file_path: Path) -> str:
        """Extract text from AI file (often contains embedded PDF)."""
        try:
            import pdfplumber
            pdf = pdfplumber.open(str(file_path))
            texts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
            pdf.close()
            return "\n\n".join(texts)
        except Exception as exc:
            log.debug("adobe_ai_text_failed", file=file_path.name, error=str(exc))
        return ""

    @staticmethod
    def _tool_name(ext: str) -> str:
        return {
            "indd": "InDesign",
            "aep": "After Effects",
            "prproj": "Premiere Pro",
            "xd": "Adobe XD",
        }.get(ext, "Adobe application")

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        """Adobe formats can't be authored — write extracted content as Markdown."""
        t_start = time.perf_counter()
        target_ext = output_path.suffix.lower().lstrip(".")
        log.info("handler_export_start", filename=output_path.name, target_format=target_ext, tier=1)

        # Write as Markdown since we can't create native Adobe files
        lines: list[str] = []
        for elem in model.elements:
            if elem.type == ElementType.HEADING:
                prefix = "#" * (elem.level or 1)
                lines.append(f"{prefix} {elem.content}")
                lines.append("")
            elif elem.type == ElementType.PARAGRAPH:
                lines.append(elem.content)
                lines.append("")
            elif elem.type == ElementType.TABLE:
                rows = elem.content
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, list):
                            lines.append("| " + " | ".join(str(c) for c in row) + " |")
                    lines.append("")
            elif elem.type == ElementType.HORIZONTAL_RULE:
                lines.append("---")
                lines.append("")

        # If output expects .md, write as-is; otherwise note the limitation
        if target_ext not in ("md", "markdown"):
            lines.insert(0, f"<!-- MarkFlow: Cannot create native .{target_ext} files. Content exported as text. -->\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        metadata = self._extract_metadata(file_path)
        fonts: list[str] = []

        # Extract font info from metadata if available
        for key in ("Fonts", "FontsUsed", "EmbeddedFonts", "Font"):
            val = metadata.get(key, "")
            if val:
                if isinstance(val, str):
                    fonts.extend(f.strip() for f in val.split(",") if f.strip())

        return {
            "document_level": {
                "extension": file_path.suffix.lower(),
                "fonts": fonts,
                "metadata": {k: v for k, v in metadata.items()
                             if k in ("Creator", "Producer", "ColorMode",
                                      "ImageWidth", "ImageHeight")},
            }
        }
