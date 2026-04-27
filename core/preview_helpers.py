"""Pure-function helpers for the preview page (v0.32.0).

Used by `api/routes/preview.py` to classify a path into a viewer
dispatch hint, a coarse file category for the metadata panel, and a
best-effort MIME type. No I/O — these helpers should never touch the
disk; they operate purely on the path's extension.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from core.preview_thumbnails import all_preview_extensions, native_preview_extensions

# ── Extension sets keyed by category ─────────────────────────────────────────

# Browser-native audio. Streamed via FileResponse with range support
# so the <audio> element can seek.
AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac",
    ".wav", ".wave", ".aif", ".aiff", ".aifc", ".weba",
    # Browser support varies for these; we still classify them as
    # audio so the sidebar shows the right icon and the action panel
    # offers a Download button.
    ".wma", ".amr", ".mpga",
}

# Browser-native video. <video> seek requires range responses; the
# /preview/content endpoint reuses FileResponse for that.
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv",
    ".flv", ".f4v", ".3gp", ".3g2", ".mpg", ".mpeg", ".ogv", ".ts",
}

PDF_EXTS = {".pdf"}

# Plain-text formats. Capped at 64 KB by the text-excerpt endpoint so
# even huge logs don't blow up the response. Syntax highlighting in
# the frontend is a nice-to-have on top — pre-formatted display works
# without it.
TEXT_EXTS = {
    # Plain text
    ".txt", ".text", ".log", ".md", ".markdown", ".rst",
    # Data
    ".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml", ".ini",
    ".csv", ".tsv", ".tab",
    # Code
    ".py", ".pyx", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".html", ".htm", ".xhtml", ".xml", ".svg", ".css", ".scss", ".sass",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1",
    ".c", ".h", ".cpp", ".cxx", ".hpp", ".cc", ".hh",
    ".java", ".kt", ".scala", ".groovy",
    ".rs", ".go", ".rb", ".php", ".pl", ".pm", ".swift",
    ".sql", ".graphql", ".gql",
    # Config
    ".conf", ".cfg", ".env", ".dockerfile", ".containerfile",
    ".gitignore", ".gitattributes", ".editorconfig",
    ".properties", ".plist",
}

# Office document family — convertible to Markdown by MarkFlow's
# converters. The viewer dispatches to the rendered-Markdown view
# when bulk_files.status == 'success' for the row.
OFFICE_EXTS = {
    ".docx", ".doc", ".dotx",
    ".xlsx", ".xls", ".xlsm", ".xltx",
    ".pptx", ".ppt", ".potx",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub",
}

ARCHIVE_EXTS = {
    ".zip", ".tar", ".gz", ".tgz", ".tar.gz",
    ".bz2", ".tbz2", ".tar.bz2",
    ".xz", ".txz", ".tar.xz",
    ".7z", ".rar", ".cab",
}


# ── Classification ───────────────────────────────────────────────────────────


def _ext_lower(path: Path | str) -> str:
    """Return the path's extension, lower-cased and dot-prefixed.
    Handles double extensions like .tar.gz by inspecting the
    last two components."""
    p = Path(path) if not isinstance(path, Path) else path
    suffixes = [s.lower() for s in p.suffixes[-2:]]
    if len(suffixes) == 2 and (
        ("".join(suffixes)) in ARCHIVE_EXTS
        or ("".join(suffixes)) in TEXT_EXTS
    ):
        return "".join(suffixes)
    return p.suffix.lower()


def get_mime_type(path: Path) -> str:
    """Best-effort MIME type from extension. Falls back to
    `application/octet-stream`. Adds a few overrides where stdlib
    mimetypes returns None or stale values:

    - .heic / .heif → image/heic
    - .avif → image/avif
    - .webp → image/webp (older Pythons return None)
    - .opus → audio/opus
    - .md → text/markdown
    """
    ext = _ext_lower(path)
    overrides = {
        ".heic": "image/heic", ".heif": "image/heif",
        ".heics": "image/heic-sequence", ".heifs": "image/heif-sequence",
        ".avif": "image/avif", ".avifs": "image/avif-sequence",
        ".webp": "image/webp",
        ".opus": "audio/opus",
        ".md": "text/markdown", ".markdown": "text/markdown",
        ".jsonl": "application/x-ndjson", ".ndjson": "application/x-ndjson",
        ".7z": "application/x-7z-compressed",
        ".rar": "application/vnd.rar",
        ".epub": "application/epub+zip",
    }
    if ext in overrides:
        return overrides[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def get_file_category(path: Path) -> str:
    """Coarse category for the metadata sidebar: one of
    `image | audio | video | document | archive | text | other`.

    Documents = PDFs + Office formats. Other categories are
    extension-based so this works on a path that may not exist on
    disk yet."""
    ext = _ext_lower(path)
    if ext in all_preview_extensions():
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in PDF_EXTS or ext in OFFICE_EXTS:
        return "document"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in TEXT_EXTS:
        return "text"
    return "other"


def classify_viewer_kind(path: Path) -> str:
    """Return the viewer dispatch hint for the frontend. One of:

    - `image` — render via /api/preview/content (native) or
      /api/preview/thumbnail (thumbnailed via PIL/rawpy/cairosvg)
    - `audio` — `<audio controls src="/api/preview/content">`
    - `video` — `<video controls src="/api/preview/content">`
    - `pdf` — `<iframe src="/api/preview/content">`
    - `text` — fetch /api/preview/text-excerpt, show in `<pre><code>`
    - `office` — Office doc; the info endpoint will refine to
      `office_with_markdown` (when bulk_files.status='success') or
      `office_no_markdown`
    - `archive` — fetch /api/preview/archive-listing, render as table
    - `unknown` — show metadata + Download button only

    The info endpoint is responsible for refining `office` based on
    the conversion state; this helper just gives the base hint.
    """
    ext = _ext_lower(path)
    # Image preview covers a lot of formats the user might not think of
    # as "image" — TIFFs of scanned receipts, EPSes from a vector tool,
    # PSDs etc. We send all of these to the image viewer because the
    # thumbnail endpoint can render them.
    if ext in all_preview_extensions():
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in OFFICE_EXTS:
        return "office"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in TEXT_EXTS:
        return "text"
    return "unknown"


def can_render_native(path: Path) -> bool:
    """True if the browser can render bytes from /api/preview/content
    directly via `<img>` / `<audio>` / `<video>` / `<iframe>` without
    a server-side thumbnail. False for formats that need
    /api/preview/thumbnail (TIFF, EPS, HEIC, RAW, SVG, PSD, …)."""
    ext = _ext_lower(path)
    if ext in native_preview_extensions():
        return True
    if ext in AUDIO_EXTS or ext in VIDEO_EXTS or ext in PDF_EXTS:
        return True
    return False
