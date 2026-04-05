"""
Image format handler — JPG, PNG, TIFF, BMP, GIF, EPS files.

Ingest:
  Extracts image metadata (dimensions, color mode, EXIF) using Pillow
  and exiftool. Produces a DocumentModel with a metadata summary heading,
  an embedded IMAGE element, and any OCR-extracted text.

Export:
  Not supported — images cannot be reconstructed from Markdown.
  Export writes extracted content as Markdown instead.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import structlog
from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
    ImageData,
)
from core.image_handler import extract_image
from formats.base import FormatHandler, register_handler

log = structlog.get_logger(__name__)


@register_handler
class ImageHandler(FormatHandler):
    """Handler for raster/vector image files: JPG, PNG, TIFF, BMP, GIF, EPS, HEIC/HEIF."""

    EXTENSIONS = ["jpg", "jpeg", "png", "tif", "tiff", "bmp", "gif", "eps", "heic", "heif", "cr2"]

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

        # ── Image dimensions & basic info via Pillow ─────────────────────────
        width, height, color_mode, pil_format = None, None, None, None
        try:
            with Image.open(str(file_path)) as img:
                width, height = img.size
                color_mode = img.mode
                pil_format = img.format
                # Store EXIF from Pillow if available
                pil_exif = {}
                exif_data = getattr(img, "_getexif", lambda: None)()
                if exif_data and isinstance(exif_data, dict):
                    from PIL.ExifTags import TAGS
                    for tag_id, value in exif_data.items():
                        tag_name = TAGS.get(tag_id, str(tag_id))
                        # Skip binary/bytes values
                        if isinstance(value, (bytes, bytearray)):
                            continue
                        try:
                            json.dumps(value)  # ensure serializable
                            pil_exif[tag_name] = value
                        except (TypeError, ValueError):
                            pil_exif[tag_name] = str(value)
                    if pil_exif:
                        model.style_data["exif"] = pil_exif
        except Exception as exc:
            log.warning("image_pillow_failed", file=file_path.name, error=str(exc))

        # ── Exiftool metadata ────────────────────────────────────────────────
        exif_meta = self._extract_metadata(file_path)
        if exif_meta:
            model.style_data["image_metadata"] = exif_meta

        # Populate document metadata
        model.metadata.title = file_path.stem
        if exif_meta:
            model.metadata.author = exif_meta.get("Artist", exif_meta.get("Creator", ""))

        # ── Build document elements ──────────────────────────────────────────

        # Title heading
        model.add_element(Element(
            type=ElementType.HEADING,
            content=file_path.name,
            level=1,
        ))

        # Image properties summary
        props: list[str] = []
        if pil_format:
            props.append(f"Format: {pil_format}")
        if width and height:
            props.append(f"Dimensions: {width} x {height} px")
        if color_mode:
            props.append(f"Color mode: {color_mode}")

        file_size = file_path.stat().st_size
        if file_size >= 1_048_576:
            props.append(f"File size: {file_size / 1_048_576:.1f} MB")
        else:
            props.append(f"File size: {file_size / 1024:.1f} KB")

        # Add select EXIF fields
        if exif_meta:
            for key in ("Make", "Model", "LensModel", "FocalLength",
                         "ExposureTime", "FNumber", "ISO",
                         "DateTimeOriginal", "CreateDate", "GPSPosition",
                         "Software", "ColorSpace", "XResolution", "YResolution"):
                if key in exif_meta and exif_meta[key]:
                    props.append(f"{key}: {exif_meta[key]}")

        if props:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(props),
                attributes={"role": "metadata_summary"},
            ))

        # ── Embed the image as an IMAGE element ──────────────────────────────
        try:
            image_bytes = file_path.read_bytes()
            fmt = ext if ext != "jpg" else "jpeg"
            hash_name, png_data, meta = extract_image(image_bytes, fmt)
            model.images[hash_name] = ImageData(
                data=png_data,
                original_format=fmt,
                width=meta.get("width") or width,
                height=meta.get("height") or height,
                alt_text=file_path.stem,
            )
            model.add_element(Element(
                type=ElementType.IMAGE,
                content="",
                attributes={
                    "src": f"assets/{hash_name}",
                    "alt": file_path.stem,
                },
            ))
        except Exception as exc:
            log.warning("image_embed_failed", file=file_path.name, error=str(exc))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content=f"[Image: {file_path.name}]",
            ))

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms,
                 width=width, height=height)
        return model

    def _extract_metadata(self, file_path: Path) -> dict[str, str]:
        """Extract metadata via exiftool (same pattern as AdobeHandler)."""
        try:
            result = subprocess.run(
                ["exiftool", "-json", "-n", str(file_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data and isinstance(data, list):
                    meta = data[0]
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
            log.debug("image_exiftool_failed", file=file_path.name, error=str(exc))
        return {}

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        """Image formats can't be authored — write extracted content as Markdown."""
        t_start = time.perf_counter()
        target_ext = output_path.suffix.lower().lstrip(".")
        log.info("handler_export_start", filename=output_path.name,
                 target_format=target_ext, tier=1)

        lines: list[str] = []
        for elem in model.elements:
            if elem.type == ElementType.HEADING:
                prefix = "#" * (elem.level or 1)
                lines.append(f"{prefix} {elem.content}")
                lines.append("")
            elif elem.type == ElementType.PARAGRAPH:
                lines.append(elem.content)
                lines.append("")
            elif elem.type == ElementType.IMAGE:
                alt = elem.content or "image"
                lines.append(f"![{alt}]({alt})")
                lines.append("")

        if target_ext not in ("md", "markdown"):
            lines.insert(0, f"<!-- MarkFlow: Cannot create native .{target_ext} files. "
                            "Content exported as text. -->\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name,
                 duration_ms=duration_ms)

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        metadata = self._extract_metadata(file_path)
        width, height, color_mode = None, None, None
        try:
            with Image.open(str(file_path)) as img:
                width, height = img.size
                color_mode = img.mode
        except Exception:
            pass

        return {
            "document_level": {
                "extension": file_path.suffix.lower(),
                "width": width,
                "height": height,
                "color_mode": color_mode,
                "metadata": {k: v for k, v in metadata.items()
                             if k in ("Make", "Model", "ColorSpace",
                                      "XResolution", "YResolution",
                                      "Software")},
            }
        }
