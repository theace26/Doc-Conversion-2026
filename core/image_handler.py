"""
Image extraction, content-hash naming, and format conversion.

- extract_image(data, original_format) → (hash_filename, png_data, metadata)
- Content-hash naming: hashlib.sha256(data).hexdigest()[:12] + ".png"
- Converts non-web formats (EMF, WMF, TIFF) to PNG via Pillow / ImageMagick
- Preserves original dimensions in returned metadata
- Images stored in output/<batch_id>/assets/
"""

import hashlib
import io
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Formats that need conversion to PNG
_CONVERT_FORMATS = {"emf", "wmf", "tiff", "tif", "bmp", "eps", "pcx"}

# Formats that are already web-compatible (still normalized for consistency)
_PASSTHROUGH_FORMATS = {"png", "jpeg", "jpg", "gif", "webp"}


def extract_image(
    data: bytes,
    original_format: str,
    source_document: str | None = None,
    image_index: int | None = None,
    *,
    raw_width: int | None = None,
    raw_height: int | None = None,
) -> tuple[str, bytes, dict[str, Any]]:
    """
    Process raw image data from a document.

    Args:
        data: Raw image bytes.
        original_format: Source format extension (e.g., "png", "emf", "jpeg").
        source_document: Path of the document this image was extracted from.
        image_index: Index of the image within the source document.
        raw_width: Pixel width hint for raw (headerless) pixel data.
        raw_height: Pixel height hint for raw (headerless) pixel data.

    Returns:
        (hash_filename, png_data, metadata)
        where hash_filename = sha256[:12].png
    """
    from PIL import Image, UnidentifiedImageError

    hash_hex = hashlib.sha256(data).hexdigest()[:12]
    hash_filename = f"{hash_hex}.png"
    fmt = original_format.lower().lstrip(".")

    metadata: dict[str, Any] = {
        "original_format": fmt,
        "hash": hash_hex,
    }

    try:
        if fmt in _CONVERT_FORMATS or fmt not in _PASSTHROUGH_FORMATS:
            png_data = _convert_to_png(data)
        else:
            png_data = _normalize_to_png(data)
    except UnidentifiedImageError:
        # Raw pixel data (e.g. PDF FlateDecode streams) — try reconstruction
        png_data = _reconstruct_raw_pixels(data, raw_width, raw_height)
        if png_data is None:
            log.debug("image_handler.raw_unidentified",
                      format=fmt,
                      source_document=source_document,
                      image_index=image_index)
            png_data = data
    except Exception as exc:
        log.warning("image_handler.convert_failed",
                    format=fmt,
                    source_document=source_document,
                    image_index=image_index,
                    error=str(exc))
        png_data = data  # Return as-is; downstream will handle gracefully

    # Extract dimensions from the result
    try:
        with Image.open(io.BytesIO(png_data)) as img:
            metadata["width"] = img.width
            metadata["height"] = img.height
    except Exception:
        if raw_width and raw_height:
            metadata["width"] = raw_width
            metadata["height"] = raw_height

    return hash_filename, png_data, metadata


def _reconstruct_raw_pixels(
    data: bytes, width: int | None, height: int | None
) -> bytes | None:
    """Attempt to reconstruct an image from raw (headerless) pixel data.

    PDF FlateDecode streams store pixel data without image headers.
    We infer the colour mode from data length vs. dimensions.

    Returns PNG bytes on success, None if reconstruction is not possible.
    """
    if not width or not height:
        return None
    from PIL import Image

    npixels = width * height
    if len(data) == npixels:
        mode = "L"
    elif len(data) == npixels * 3:
        mode = "RGB"
    elif len(data) == npixels * 4:
        mode = "CMYK"
    else:
        return None

    try:
        img = Image.frombytes(mode, (width, height), data)
        if mode == "CMYK":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _convert_to_png(data: bytes) -> bytes:
    """Convert any Pillow-readable image bytes to PNG."""
    from PIL import Image

    buf_in = io.BytesIO(data)
    buf_out = io.BytesIO()
    with Image.open(buf_in) as img:
        if img.mode not in ("RGB", "RGBA", "L", "P"):
            img = img.convert("RGBA")
        img.save(buf_out, format="PNG")
    return buf_out.getvalue()


def _normalize_to_png(data: bytes) -> bytes:
    """Re-encode a web-compatible image as PNG for consistent storage."""
    from PIL import Image

    buf_in = io.BytesIO(data)
    buf_out = io.BytesIO()
    with Image.open(buf_in) as img:
        # Preserve transparency when present
        if img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")
        elif img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        img.save(buf_out, format="PNG")
    return buf_out.getvalue()
