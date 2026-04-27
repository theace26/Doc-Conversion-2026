"""Shared thumbnail-generation machinery (v0.32.0 refactor).

Originally lived inline in `api/routes/analysis.py`; extracted here so
both the source_file-id-keyed analysis endpoint AND the new
path-keyed preview endpoint (`api/routes/preview.py`) can share the
same cache and the same dispatching logic.

Public surface:
    - `is_previewable(ext)` / `needs_thumbnail(ext)`     — predicates
    - `get_cached_thumbnail(path)`                       — async LRU
    - `THUMB_MAX_PX`, `THUMB_JPEG_QUALITY`               — constants
    - The `_PREVIEW_EXTS` sets for callers that need to introspect
      the supported extension lists

Cache key is path-based (resolved string + mtime_ns + size) so two
callers asking for a thumbnail of the same file share the cache hit
regardless of how they identified the file (source_file_id vs raw
path). Eviction is LRU at THUMB_CACHE_SIZE.

Errors: `get_cached_thumbnail` raises:
    - OSError   — the file isn't accessible (stat failed, missing)
    - RuntimeError — thumbnail generation failed (PIL / rawpy /
      cairosvg error). The route layer should translate to HTTP
      404 / 500 respectively.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


# ── Format dispatch sets ─────────────────────────────────────────────────────

# Browser renders these natively — stream the raw bytes unchanged.
_NATIVE_PREVIEW_EXTS = {
    # JPEG family
    ".jpg", ".jpeg", ".jfif", ".jpe",
    # PNG family
    ".png", ".apng",
    # Other native formats
    ".gif", ".bmp", ".dib", ".webp",
    # Modern formats supported by all recent browsers
    ".avif", ".avifs",
    # Icon / cursor formats
    ".ico", ".cur",
}

# Browser CAN'T render these — generate a JPEG thumbnail via PIL.
# .eps / .ps use PIL's EpsImagePlugin which shells out to Ghostscript
# (/usr/bin/gs). .psd is read as the flat composite (good enough for
# preview).
_THUMBNAIL_PREVIEW_EXTS = {
    # TIFF family
    ".tif", ".tiff",
    # PostScript family (rasterized via Ghostscript)
    ".eps", ".ps",
    # JPEG 2000 family
    ".jp2", ".j2k", ".jpx", ".jpc", ".jpf", ".j2c",
    # Netpbm family
    ".ppm", ".pgm", ".pbm", ".pnm",
    # Targa family (TrueVision TGA)
    ".tga", ".icb", ".vda", ".vst",
    # SGI family
    ".sgi", ".rgb", ".rgba", ".bw",
    # Other photo/raster formats PIL decodes natively
    ".pcx", ".dds", ".icns", ".psd",
    # v0.31.3: HEIC / HEIF (modern phone-camera default). pillow-heif
    # registers itself as a PIL opener at module load (see below) so
    # these flow through the standard PIL `Image.open()` path.
    ".heic", ".heif", ".heics", ".heifs",
}

# v0.31.3: RAW camera formats — separate set because they don't go
# through PIL. Decoded via `rawpy` (ships LibRaw in wheels), the
# resulting numpy array is converted to a PIL Image, then the same
# thumbnail pipeline takes over.
_RAW_PREVIEW_EXTS = {
    # Canon
    ".cr2", ".cr3", ".crw",
    # Nikon
    ".nef", ".nrw",
    # Sony
    ".arw", ".srf", ".sr2",
    # Fuji / Olympus / Panasonic / Pentax / Samsung
    ".raf", ".orf", ".rw2", ".pef", ".srw",
    # Adobe Digital Negative (cross-vendor open standard)
    ".dng",
    # Kodak / Sigma / Hasselblad / Leica / Mamiya / Phase One / Epson
    ".kdc", ".dcr", ".x3f", ".3fr", ".fff", ".mef", ".mos", ".raw", ".rwl", ".erf",
}

# v0.31.3: SVG — rasterized via cairosvg (no XSS surface because we
# return JPEG bytes, not the original SVG document).
_SVG_PREVIEW_EXTS = {".svg", ".svgz"}

_ALL_PREVIEW_EXTS = (
    _NATIVE_PREVIEW_EXTS | _THUMBNAIL_PREVIEW_EXTS
    | _RAW_PREVIEW_EXTS | _SVG_PREVIEW_EXTS
)

# v0.31.3: Register pillow-heif as a PIL opener at module import so
# .heic / .heif files get the same `Image.open()` path TIFF/PSD use.
# Quietly tolerate the import failing — base image without the dep
# still serves every other format.
try:
    import pillow_heif as _pillow_heif  # type: ignore[import-not-found]
    _pillow_heif.register_heif_opener()
except Exception as _exc:  # pragma: no cover — defensive
    log.warning(
        "preview_thumbnails.pillow_heif_unavailable",
        error=f"{type(_exc).__name__}: {_exc}",
    )


THUMB_MAX_PX = 400
THUMB_JPEG_QUALITY = 78
THUMB_CACHE_SIZE = 64  # ~13 MB at 200 KB avg per thumb — bounded and small
_thumb_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


# ── Public API ───────────────────────────────────────────────────────────────


def _ext_lower(ext: str) -> str:
    return ("." + ext.lstrip(".")).lower()


def is_previewable(ext: str) -> bool:
    """True if a thumbnail/preview can be produced for this extension."""
    return _ext_lower(ext) in _ALL_PREVIEW_EXTS


def needs_thumbnail(ext: str) -> bool:
    """True if the extension requires server-side thumbnailing (vs.
    streaming raw bytes the browser can render natively)."""
    e = _ext_lower(ext)
    return (
        e in _THUMBNAIL_PREVIEW_EXTS
        or e in _RAW_PREVIEW_EXTS
        or e in _SVG_PREVIEW_EXTS
    )


def native_preview_extensions() -> set[str]:
    """Lower-case, dot-prefixed set of extensions a browser can render
    directly via `<img src=...>` without a server-side thumbnail."""
    return set(_NATIVE_PREVIEW_EXTS)


def all_preview_extensions() -> set[str]:
    """Every extension supported by the preview pipeline (native +
    thumbnailed + RAW + SVG)."""
    return set(_ALL_PREVIEW_EXTS)


# ── Thumbnail generators ─────────────────────────────────────────────────────


def _generate_thumbnail_sync(path: Path) -> bytes:
    """Open `path` with PIL, thumbnail to THUMB_MAX_PX on the longest
    edge, return JPEG bytes. Runs in a worker thread via
    asyncio.to_thread; must not touch async state.

    Dispatches to specialized helpers for RAW (rawpy) and SVG
    (cairosvg) formats; HEIC/HEIF flow through the standard PIL path
    via the pillow-heif opener registered at module load.
    """
    ext = _ext_lower(path.suffix)
    if ext in _RAW_PREVIEW_EXTS:
        return _generate_raw_thumbnail_sync(path)
    if ext in _SVG_PREVIEW_EXTS:
        return _generate_svg_thumbnail_sync(path)

    from PIL import Image  # lazy — heavy module

    with Image.open(str(path)) as img:
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
        return buf.getvalue()


def _generate_raw_thumbnail_sync(path: Path) -> bytes:
    """Decode a RAW camera file via `rawpy`, downsample, return JPEG
    bytes. v0.31.3.

    RAW files carry an embedded JPEG preview (typically 160-1600 px
    on the longest edge); we use `rawpy.extract_thumb()` when
    available since it's ~50× faster than full demosaicing. If
    extraction fails (older RAW format with no embedded preview), we
    fall back to a half-sized demosaic — still much faster than full
    res.
    """
    import rawpy  # type: ignore[import-not-found]
    from PIL import Image

    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                with Image.open(BytesIO(thumb.data)) as img:
                    img.load()
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format="JPEG",
                             quality=THUMB_JPEG_QUALITY, optimize=True)
                    return buf.getvalue()
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                img = Image.fromarray(thumb.data)
                img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, format="JPEG",
                         quality=THUMB_JPEG_QUALITY, optimize=True)
                return buf.getvalue()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            pass

        # No embedded preview — half-size demosaic. `half_size=True`
        # skips the bayer interpolation cost.
        rgb = raw.postprocess(half_size=True, no_auto_bright=False, output_bps=8)
        img = Image.fromarray(rgb)
        img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG",
                 quality=THUMB_JPEG_QUALITY, optimize=True)
        return buf.getvalue()


def _generate_svg_thumbnail_sync(path: Path) -> bytes:
    """Rasterize an SVG to JPEG via `cairosvg` → PIL (v0.31.3).

    Security: the output is raster pixels, NOT the original SVG
    document, so any embedded `<script>` / event handlers / external
    `<image>` references are inert by the time the browser sees the
    response.

    Bomb defense: cap the rasterized output dimensions at
    THUMB_MAX_PX (longest edge) via cairosvg's `output_width`.
    """
    import cairosvg  # type: ignore[import-not-found]
    from PIL import Image

    png_bytes = cairosvg.svg2png(
        url=str(path),
        output_width=THUMB_MAX_PX,
    )
    with Image.open(BytesIO(png_bytes)) as img:
        img.load()
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img.convert("RGB"))
            img = background
        if max(img.size) > THUMB_MAX_PX:
            img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG",
                 quality=THUMB_JPEG_QUALITY, optimize=True)
        return buf.getvalue()


# ── Cached entry point ───────────────────────────────────────────────────────


async def get_cached_thumbnail(path: Path) -> bytes:
    """Return cached or freshly-rendered JPEG thumbnail bytes.

    Cache key = (resolved_path_str, st_mtime_ns, st_size). Path-based
    so callers identifying the same file via different identifiers
    (source_file_id vs raw path) share the cache hit. Any edit to
    the file changes the key so stale thumbs are never served. LRU
    eviction at THUMB_CACHE_SIZE entries.

    Raises:
        OSError: file not accessible (stat failed)
        RuntimeError: thumbnail generation failed (PIL / rawpy /
            cairosvg). The exception's `__cause__` carries the
            original error; the message is suitable for surfacing
            in HTTP 500 responses.
    """
    try:
        stat = path.stat()
    except OSError:
        raise

    try:
        resolved = str(path.resolve())
    except (OSError, RuntimeError):
        # Fall back to the unresolved path — cache key still bounded
        # but we lose dedup across symlinks. Acceptable.
        resolved = str(path)

    cache_key = (resolved, stat.st_mtime_ns, stat.st_size)
    hit = _thumb_cache.get(cache_key)
    if hit is not None:
        _thumb_cache.move_to_end(cache_key)
        return hit

    try:
        thumb_bytes = await asyncio.to_thread(_generate_thumbnail_sync, path)
    except Exception as exc:
        log.warning(
            "preview_thumbnails.generation_failed",
            path=str(path),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise RuntimeError(
            f"Thumbnail generation failed: {type(exc).__name__}: {exc}"
        ) from exc

    _thumb_cache[cache_key] = thumb_bytes
    _thumb_cache.move_to_end(cache_key)
    while len(_thumb_cache) > THUMB_CACHE_SIZE:
        _thumb_cache.popitem(last=False)
    return thumb_bytes
