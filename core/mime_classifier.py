"""
MIME type detection and file category classification.

Uses python-magic (libmagic) for content-based MIME detection with extension
fallback for types libmagic misses. No dependencies on other MarkFlow modules.
"""

from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

MIME_TO_CATEGORY: dict[str, str] = {
    # Disk images
    "application/x-iso9660-image": "disk_image",
    "application/x-raw-disk-image": "disk_image",
    "application/x-virtualbox-vdi": "disk_image",
    "application/x-vmdk": "disk_image",
    # Raster images
    "image/jpeg": "raster_image",
    "image/png": "raster_image",
    "image/tiff": "raster_image",
    "image/bmp": "raster_image",
    "image/gif": "raster_image",
    "image/webp": "raster_image",
    "image/heic": "raster_image",
    "image/avif": "raster_image",
    # Vector images
    "image/svg+xml": "vector_image",
    "application/postscript": "vector_image",
    # Video
    "video/mp4": "video",
    "video/x-matroska": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video",
    "video/x-ms-wmv": "video",
    "video/webm": "video",
    # Audio
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/flac": "audio",
    "audio/aac": "audio",
    "audio/ogg": "audio",
    # Archives
    "application/zip": "archive",
    "application/x-tar": "archive",
    "application/gzip": "archive",
    "application/x-7z-compressed": "archive",
    "application/x-rar-compressed": "archive",
    # Executables
    "application/x-dosexec": "executable",
    "application/x-msi": "executable",
    "application/x-executable": "executable",
    "application/x-sharedlib": "executable",
    # Databases
    "application/x-sqlite3": "database",
    "application/msaccess": "database",
    # Fonts
    "font/ttf": "font",
    "font/otf": "font",
    "font/woff": "font",
    "font/woff2": "font",
    "application/font-woff": "font",
}

_EXT_FALLBACK: dict[str, str] = {
    "iso": "disk_image", "img": "disk_image", "vhd": "disk_image",
    "vmdk": "disk_image", "dmg": "disk_image",
    "jpg": "raster_image", "jpeg": "raster_image", "png": "raster_image",
    "tiff": "raster_image", "tif": "raster_image", "bmp": "raster_image",
    "gif": "raster_image", "heic": "raster_image", "webp": "raster_image",
    "svg": "vector_image", "eps": "vector_image",
    "mp4": "video", "mkv": "video", "mov": "video",
    "avi": "video", "wmv": "video", "webm": "video", "m4v": "video",
    "flv": "video",
    "mp3": "audio", "wav": "audio", "flac": "audio",
    "aac": "audio", "ogg": "audio", "wma": "audio", "opus": "audio",
    "m4a": "audio",
    "zip": "archive", "tar": "archive", "gz": "archive",
    "7z": "archive", "rar": "archive", "cab": "archive",
    "exe": "executable", "msi": "executable", "dll": "executable",
    "so": "executable",
    "sqlite": "database", "db": "database", "mdb": "database",
    "accdb": "database",
    "ttf": "font", "otf": "font", "woff": "font", "woff2": "font",
    "py": "code", "js": "code", "ts": "code", "cs": "code",
    "cpp": "code", "java": "code", "c": "code", "h": "code",
    "rb": "code", "go": "code", "rs": "code", "sh": "code",
    "bat": "code", "ps1": "code", "php": "code", "html": "code",
    "css": "code", "json": "code", "xml": "code", "yaml": "code",
    "yml": "code", "toml": "code", "ini": "code", "cfg": "code",
    "md": "code", "txt": "code", "log": "code", "sql": "code",
}


def detect_mime(path: Path) -> str:
    """Detect MIME type using libmagic. Returns 'application/octet-stream' on failure."""
    try:
        import magic
        return magic.from_file(str(path), mime=True)
    except Exception as exc:
        log.debug("mime_detect_failed", path=str(path), error=str(exc))
        return "application/octet-stream"


def classify(path: Path, mime_type: str | None = None) -> tuple[str, str]:
    """
    Returns (mime_type, category).
    Detects MIME if not provided. Falls back to extension heuristic if MIME unknown.
    """
    if mime_type is None:
        mime_type = detect_mime(path)

    category = MIME_TO_CATEGORY.get(mime_type)
    if category:
        return mime_type, category

    ext = path.suffix.lower().lstrip(".")
    return mime_type, _EXT_FALLBACK.get(ext, "unknown")
