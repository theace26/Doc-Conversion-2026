"""File preview API (v0.32.0).

Path-keyed endpoints for the preview page (`/static/preview.html`).
Where the analysis-route preview endpoint is keyed by
`source_file_id` and limited to image previews, this router accepts
absolute container paths and serves a much broader set of file
types: raw bytes (audio, video, PDF, native images), text excerpts,
archive listings, server-side thumbnails (TIFF, EPS, HEIC, RAW,
SVG, PSD via the shared `core.preview_thumbnails` cache), and
already-converted Markdown.

Endpoints (all OPERATOR+ gated):
    GET /api/preview/info           — composite metadata + status + siblings
    GET /api/preview/content        — stream raw bytes (range supported)
    GET /api/preview/thumbnail      — server-rendered JPEG thumbnail
    GET /api/preview/text-excerpt   — first N bytes UTF-8 decoded
    GET /api/preview/archive-listing— zip/tar/7z entries (capped 500)
    GET /api/preview/markdown-output— converted Markdown (404 if none)

All endpoints require an absolute container path under one of the
allowed mount roots (verified by
`core.path_utils.is_path_under_allowed_root`). Paths outside the
allow-list return HTTP 400 — never 404 — so traversal attempts can't
infer "interesting" directories from missing-vs-blocked responses.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tarfile
import time
import urllib.parse
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from core.auth import AuthenticatedUser, UserRole, require_role
from core.db.connection import db_fetch_one, db_fetch_all
from core.path_utils import is_path_under_allowed_root
from core.preview_helpers import (
    ACTION_ANALYZE,
    ACTION_CONVERT,
    ACTION_NONE,
    ACTION_TRANSCRIBE,
    AUDIO_EXTS,
    OFFICE_EXTS,
    TEXT_EXTS,
    classify_viewer_kind,
    get_file_category,
    get_mime_type,
    pick_action_for_path,
)
from core.preview_thumbnails import (
    get_cached_thumbnail,
    is_previewable as is_thumbnail_eligible,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/preview", tags=["preview"])


# ── Constants ────────────────────────────────────────────────────────────────

# Inline-content streaming cap. Large videos use HTTP range requests
# from the browser's <video> element so this only fires on weird
# unbounded fetches (e.g. a curl with no Range header against a 4 GB
# video). 500 MB is comfortably above any reasonable inline preview
# but below "rememberable runaway".
_CONTENT_INLINE_MAX_BYTES = 500 * 1024 * 1024

# Text excerpt cap. 64 KB is enough to see the shape of a log /
# config / source file without making the response slow.
_TEXT_EXCERPT_DEFAULT_BYTES = 64 * 1024
_TEXT_EXCERPT_HARD_MAX_BYTES = 512 * 1024

# Archive listing cap. The Pipeline Files page already shows the
# archive's top-line stats; the preview page is mostly for
# orientation, not exhaustive enumeration.
_ARCHIVE_LISTING_MAX_ENTRIES = 500

# Sibling listing cap. The preview page is one-file-detail, not a
# file browser — 200 entries is generous for orientation. The
# pipeline-files page is the right tool for big-folder browsing.
_SIBLING_LISTING_MAX = 200

# Sibling listing wall-clock cap. Slow SMB / NFS shares can take
# tens of seconds to enumerate a thousand-file directory. Cap so a
# slow share doesn't pin the request thread indefinitely.
_SIBLING_SCAN_MAX_SECONDS = 10.0


# ── Path validation ──────────────────────────────────────────────────────────


def _normalize_path(raw: str | None) -> Path:
    """Validate, decode, and normalize the `?path=` query param.

    Raises HTTPException(400) on:
        - missing / empty
        - Windows-style backslash path separators
        - drive-letter prefix (e.g. `C:\\foo`)
        - relative path (must be absolute)
        - path outside the allowed mount roots

    Returns the resolved Path. The caller should stat() it to check
    existence (we don't 404 here so the info endpoint can return
    `exists: false` for paths that resolve safely but aren't on
    disk yet — useful for preview of files that were just deleted).
    """
    if not raw:
        raise HTTPException(status_code=400, detail="path query parameter is required")

    # Single decode — paths arrive percent-encoded from the URL.
    # Defending against double-decoding ambiguity: if the first
    # decode contains a `%`, that's likely a literal `%` in the
    # filename and we keep it as-is.
    decoded = urllib.parse.unquote(raw)

    # Reject Windows-shaped paths defensively. The user's host is
    # Windows but the container only ever sees Linux paths via the
    # Docker mounts. A backslash in the path means something went
    # wrong upstream.
    if "\\" in decoded:
        raise HTTPException(
            status_code=400,
            detail="path contains backslash separators; use forward slashes",
        )
    if len(decoded) >= 2 and decoded[1] == ":" and decoded[0].isalpha():
        raise HTTPException(
            status_code=400,
            detail="path starts with a Windows drive letter; use the container path under /host/<letter>",
        )

    decoded = decoded.rstrip("/")
    if not decoded.startswith("/"):
        raise HTTPException(
            status_code=400,
            detail="path must be absolute (start with /)",
        )

    p = Path(decoded)
    if not is_path_under_allowed_root(p):
        log.warning(
            "preview.path_outside_allowed_roots",
            path=decoded,
        )
        raise HTTPException(
            status_code=400,
            detail="path is outside the allowed mount roots",
        )
    return p


# ── DB lookups (composite info endpoint) ─────────────────────────────────────


async def _lookup_source_file(source_path: str) -> dict | None:
    row = await db_fetch_one(
        """SELECT id, source_path, content_hash, file_size_bytes,
                  mime_type, file_category, lifecycle_status,
                  marked_for_deletion_at, moved_to_trash_at,
                  created_at, updated_at
             FROM source_files
            WHERE source_path = ?""",
        (source_path,),
    )
    return dict(row) if row else None


async def _lookup_latest_bulk_file(source_path: str) -> dict | None:
    """Return the most-recently-touched bulk_files row for this path.
    Multiple rows can exist (one per bulk job that processed the
    file); we want the most recent so the operator sees current
    state, not historical."""
    row = await db_fetch_one(
        """SELECT id, job_id, source_path, output_path, file_ext,
                  file_size_bytes, content_hash, status, error_msg,
                  converted_at, indexed_at, ocr_confidence_mean,
                  ocr_skipped_reason, mime_type, file_category,
                  lifecycle_status
             FROM bulk_files
            WHERE source_path = ?
         ORDER BY COALESCE(converted_at, '') DESC,
                  COALESCE(indexed_at, '') DESC,
                  id DESC
            LIMIT 1""",
        (source_path,),
    )
    return dict(row) if row else None


async def _lookup_analysis_row(source_path: str) -> dict | None:
    row = await db_fetch_one(
        """SELECT id, source_path, status, batch_id, batched_at,
                  analyzed_at, description, extracted_text,
                  provider_id, model, error, retry_count, tokens_used,
                  enqueued_at
             FROM analysis_queue
            WHERE source_path = ?
         ORDER BY enqueued_at DESC
            LIMIT 1""",
        (source_path,),
    )
    return dict(row) if row else None


async def _lookup_file_flags(source_file_id: str | None) -> list[dict]:
    if not source_file_id:
        return []
    rows = await db_fetch_all(
        """SELECT id, flagged_by_email, reason, note, status,
                  expires_at, created_at, resolved_at,
                  resolved_by_email, resolution_note
             FROM file_flags
            WHERE source_file_id = ? AND status = 'active'
         ORDER BY created_at DESC""",
        (source_file_id,),
    )
    return [dict(r) for r in rows]


def _list_siblings_sync(parent: Path, current: Path) -> dict:
    """Synchronous sibling listing. Capped at _SIBLING_LISTING_MAX
    entries and _SIBLING_SCAN_MAX_SECONDS wall-clock. Runs in a
    worker thread via asyncio.to_thread.

    Returns dict with `total`, `current_index`, `truncated`, and
    `files` keys. Sorted alphabetically. Hidden files (.*) are
    included so operators can see config / .DS_Store / etc.
    """
    if not parent.exists() or not parent.is_dir():
        return {
            "total": 0, "current_index": -1, "truncated": False, "files": [],
        }

    deadline = time.monotonic() + _SIBLING_SCAN_MAX_SECONDS
    truncated = False
    raw_entries: list[tuple[str, Path]] = []
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if time.monotonic() > deadline:
                    truncated = True
                    break
                raw_entries.append((entry.name, Path(entry.path)))
    except OSError as exc:
        log.warning(
            "preview.sibling_listing_failed",
            parent=str(parent),
            error=f"{type(exc).__name__}: {exc}",
        )
        return {
            "total": 0, "current_index": -1, "truncated": False,
            "files": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    raw_entries.sort(key=lambda t: t[0].lower())
    total = len(raw_entries)
    current_name = current.name
    current_index = -1
    for idx, (name, _) in enumerate(raw_entries):
        if name == current_name:
            current_index = idx
            break

    capped = raw_entries[: _SIBLING_LISTING_MAX]
    if len(raw_entries) > _SIBLING_LISTING_MAX:
        truncated = True

    files: list[dict] = []
    for name, p in capped:
        try:
            st = p.stat()
            is_dir = p.is_dir()
            size = st.st_size if not is_dir else None
            mtime_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            is_dir = False
            size = None
            mtime_iso = None
        files.append({
            "name": name,
            "path": str(p),
            "is_dir": is_dir,
            "size_bytes": size,
            "mtime_iso": mtime_iso,
            "is_current": name == current_name,
        })

    return {
        "total": total,
        "current_index": current_index,
        "truncated": truncated,
        "files": files,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/info")
async def get_preview_info(
    path: str = Query(..., description="Absolute container path"),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Composite metadata for the preview page.

    Returns file metadata + source_files registry row (if any) +
    latest bulk_files conversion row (if any) + latest analysis_queue
    row (if any) + active file_flags + sibling listing.

    The `viewer_kind` field is the dispatch hint for the frontend:
    `image | audio | video | pdf | text | office_with_markdown |
    office_no_markdown | archive | unknown`. The Office variant is
    refined here based on whether a successful conversion exists.

    If the path resolves under the allowed roots but doesn't exist
    on disk, returns `exists: false` rather than 404 — useful for
    showing recently-deleted files.
    """
    p = _normalize_path(path)
    source_path_str = str(p)

    # Synchronous stat() — Path is small. Worker thread overhead
    # would dominate.
    exists = p.exists()
    is_file = p.is_file() if exists else False
    size_bytes: int | None = None
    mtime_iso: str | None = None
    if is_file:
        try:
            st = p.stat()
            size_bytes = st.st_size
            mtime_iso = datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc,
            ).isoformat()
        except OSError as exc:
            log.warning(
                "preview.info_stat_failed",
                path=source_path_str,
                error=f"{type(exc).__name__}: {exc}",
            )

    # DB lookups in parallel — they're independent and aiosqlite
    # serializes at the connection level anyway.
    source_file, bulk_file, analysis = await asyncio.gather(
        _lookup_source_file(source_path_str),
        _lookup_latest_bulk_file(source_path_str),
        _lookup_analysis_row(source_path_str),
    )
    flags = await _lookup_file_flags(
        source_file["id"] if source_file else None
    )

    # Sibling listing in a worker thread — directory scans on slow
    # mounts can be unpredictable.
    siblings = await asyncio.to_thread(_list_siblings_sync, p.parent, p)

    # viewer_kind dispatch with refinement for Office documents.
    base_viewer_kind = classify_viewer_kind(p)
    viewer_kind = base_viewer_kind
    if base_viewer_kind == "office":
        if bulk_file and (bulk_file.get("status") == "success"):
            viewer_kind = "office_with_markdown"
        else:
            viewer_kind = "office_no_markdown"

    log.info(
        "preview.info",
        user=user.email,
        path=source_path_str,
        viewer_kind=viewer_kind,
        has_source_file=bool(source_file),
        has_conversion=bool(bulk_file),
        has_analysis=bool(analysis),
        flag_count=len(flags),
    )

    # Stable hash of the fields that, when changed, should trigger the
    # "page has been updated" banner on the frontend. Background work
    # (force-action, normal pipeline ticks) eventually flips one of
    # these; the frontend polls /info on visibility-change and compares
    # the stored version against the new one.
    version_parts = [
        str(size_bytes),
        str(mtime_iso),
        str(viewer_kind),
        str((bulk_file or {}).get("status")),
        str((bulk_file or {}).get("converted_at")),
        str((bulk_file or {}).get("output_path")),
        str((analysis or {}).get("status")),
        str((analysis or {}).get("analyzed_at")),
        str((analysis or {}).get("description") or "")[:64],
        str(len(flags)),
    ]
    info_version = hashlib.sha256(
        "|".join(version_parts).encode("utf-8"),
    ).hexdigest()[:16]

    return {
        "path": source_path_str,
        "name": p.name,
        "parent_dir": str(p.parent),
        "exists": exists,
        "is_file": is_file,
        "size_bytes": size_bytes,
        "mtime_iso": mtime_iso,
        "mime_type": get_mime_type(p) if is_file else None,
        "extension": p.suffix.lower(),
        "category": get_file_category(p),
        "viewer_kind": viewer_kind,
        "source_file": source_file,
        "conversion": bulk_file,
        "analysis": analysis,
        "flags": flags,
        "siblings": siblings,
        "action": pick_action_for_path(p),  # force-action verb hint
        "info_version": info_version,
    }


def _content_not_found_html(path_str: str, reason: str) -> HTMLResponse:
    """Render a friendly HTML error for missing-file content requests.

    The /api/preview/content endpoint is normally invoked from
    `<img>` / `<audio>` / `<video>` / `<a href>` inside the preview
    page, where a 404 JSON response is invisible (the browser just
    doesn't render the asset). But operators occasionally land on
    the URL directly — clicking "Open in new tab" against a stale
    registry row, or following a bookmark — and a raw
    `{"detail":"file not found"}` blob is a hostile UX.

    This wrapper returns a small standalone page with the file's
    container path, the reason it couldn't be served, and a link
    back to the preview view (which itself handles missing files
    gracefully).
    """
    # Defensive escaping. The path comes from the URL but we own the
    # template so html.escape is sufficient.
    import html as _html
    safe_path = _html.escape(path_str)
    safe_reason = _html.escape(reason)
    preview_link = (
        "/static/preview.html?path=" + urllib.parse.quote(path_str, safe="")
    )
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>File not found — MarkFlow</title>
  <link rel="stylesheet" href="/static/markflow.css">
  <style>
    body {{ background: #0b0b14; color: #eee; font-family: system-ui, sans-serif;
            margin: 0; padding: 2rem; }}
    .wrap {{ max-width: 36rem; margin: 4rem auto; padding: 1.5rem;
             background: #161624; border: 1px solid #2b2b3f; border-radius: 8px; }}
    h1 {{ margin: 0 0 0.4rem; font-size: 1.2rem; color: #fca5a5; }}
    .reason {{ color: #aaa; font-size: 0.9rem; margin-bottom: 1rem; }}
    .path {{ font-family: ui-monospace, monospace; font-size: 0.82rem;
             padding: 0.5rem 0.6rem; background: #0b0b14; border-radius: 4px;
             color: #eee; word-break: break-all; margin-bottom: 1rem; }}
    .hint {{ color: #aaa; font-size: 0.85rem; margin-bottom: 1rem;
             line-height: 1.5; }}
    .btns {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    .btn {{ display: inline-block; padding: 0.45rem 0.85rem;
            border-radius: 5px; text-decoration: none; font-size: 0.88rem;
            border: 1px solid #2b2b3f; color: #eee; }}
    .btn.primary {{ background: #4f46e5; border-color: #4f46e5; }}
    .btn:hover {{ background: rgba(255,255,255,0.06); }}
    .btn.primary:hover {{ background: #4338ca; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>File not found</h1>
    <div class="reason">{safe_reason}</div>
    <div class="path">{safe_path}</div>
    <div class="hint">
      The MarkFlow registry has a record of this file but it could not be
      read from disk. The file may have been moved, renamed, or deleted
      since the last source scan. The preview page can still show its
      metadata and any prior conversion / analysis results.
    </div>
    <div class="btns">
      <a class="btn primary" href="{preview_link}">← Back to file preview</a>
      <a class="btn" href="/static/pipeline-files.html">Pipeline Files</a>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=body, status_code=404)


def _wants_html(request: Request) -> bool:
    """True when the request looks like a browser navigation (Accept
    header contains text/html). False for fetch/XHR / range requests
    from <audio>/<video>/<img> elements, which prefer the JSON 404
    so they can fail silently."""
    accept = (request.headers.get("accept") or "").lower()
    return "text/html" in accept


@router.get("/content")
async def get_preview_content(
    request: Request,
    path: str = Query(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
):
    """Stream the file at `path` for inline preview.

    Reuses FastAPI's FileResponse, which honors HTTP Range headers
    out of the box — that's what `<video>` and `<audio>` use for
    seeking. Browsers send `Range: bytes=0-` on the first request,
    so the streaming-vs-full distinction is handled transparently.

    The 500 MB inline cap fires only on naive unbounded fetches
    (e.g., a script doing a plain `curl` with no Range header
    against a 4 GB video). Browsers always send Range, so this is
    a defense-in-depth bound rather than a normal-traffic concern.

    On missing files: returns a styled HTML error page when the
    request comes from a browser navigation (Accept: text/html),
    or the standard JSON 404 for media-element / fetch consumers.
    """
    p = _normalize_path(path)
    if not p.exists() or not p.is_file():
        if _wants_html(request):
            return _content_not_found_html(
                str(p),
                "The file does not exist on disk."
                if not p.exists()
                else "The path resolves to a directory, not a file.",
            )
        raise HTTPException(status_code=404, detail="file not found")

    try:
        size = p.stat().st_size
    except OSError as exc:
        if _wants_html(request):
            return _content_not_found_html(
                str(p), f"File not accessible: {type(exc).__name__}: {exc}",
            )
        raise HTTPException(
            status_code=404, detail=f"file not accessible: {exc}",
        ) from exc

    # The cap intentionally fires only when there's no Range header.
    # Defaulting to FileResponse covers the streaming case; the cap
    # message tells the operator how to fetch the file safely.
    if size > _CONTENT_INLINE_MAX_BYTES:
        # Note: a streaming-aware client (browser <video>) sends
        # Range and gets through fine; FileResponse's 206 path is
        # unaffected by this check. This branch is unreached for
        # range requests because Starlette handles them before our
        # handler returns. We surface a hint anyway.
        log.info(
            "preview.content_large_file",
            user=user.email, path=str(p), size=size,
        )

    log.info(
        "preview.content",
        user=user.email,
        path=str(p),
        size=size,
    )
    return FileResponse(
        path=str(p),
        media_type=get_mime_type(p),
        filename=p.name,
    )


@router.get("/thumbnail")
async def get_preview_thumbnail(
    path: str = Query(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> Response:
    """Server-rendered JPEG thumbnail for image-like files.

    Reuses the shared LRU cache in `core.preview_thumbnails`, so a
    file thumbnailed here and via the source_file_id-keyed analysis
    endpoint share the same cache entry (cache key is path-based).

    Returns 404 if the extension isn't in the supported preview
    set, 500 if PIL/rawpy/cairosvg fails on the bytes.
    """
    p = _normalize_path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if not is_thumbnail_eligible(p.suffix):
        raise HTTPException(
            status_code=404,
            detail="thumbnail not available for this file type",
        )

    try:
        thumb_bytes = await get_cached_thumbnail(p)
    except OSError as exc:
        raise HTTPException(
            status_code=404, detail=f"file not accessible: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=thumb_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/text-excerpt")
async def get_preview_text_excerpt(
    path: str = Query(...),
    max_bytes: int = Query(
        _TEXT_EXCERPT_DEFAULT_BYTES,
        ge=1024, le=_TEXT_EXCERPT_HARD_MAX_BYTES,
    ),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return the first `max_bytes` of `path` as UTF-8 text.

    Decoded with `errors='replace'` so binary-ish files don't 500
    here; the frontend can show the (possibly mostly-replacement-
    char) excerpt and let the operator decide. The endpoint is
    extension-gated to TEXT_EXTS / OFFICE_EXTS / `unknown` so a
    `.mp4` doesn't accidentally get decoded.
    """
    p = _normalize_path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    ext = p.suffix.lower()
    # Don't decode known-binary formats. The TEXT_EXTS list covers
    # the genuine text formats; we permit `unknown` extensions so an
    # operator can still inspect a .dat file in the off chance it's
    # plain text.
    is_text_safe = (
        ext in TEXT_EXTS
        or get_file_category(p) in {"text", "other"}
    )
    if not is_text_safe:
        raise HTTPException(
            status_code=400,
            detail=f"text excerpt not available for category {get_file_category(p)}",
        )

    try:
        size = p.stat().st_size
    except OSError as exc:
        raise HTTPException(
            status_code=404, detail=f"file not accessible: {exc}",
        ) from exc

    def _read() -> bytes:
        with open(p, "rb") as f:
            return f.read(max_bytes)

    raw = await asyncio.to_thread(_read)
    text = raw.decode("utf-8", errors="replace")

    log.info(
        "preview.text_excerpt",
        user=user.email,
        path=str(p),
        bytes_requested=max_bytes,
        bytes_returned=len(raw),
        full_size=size,
    )
    return {
        "path": str(p),
        "text": text,
        "bytes_returned": len(raw),
        "full_size_bytes": size,
        "truncated": size > len(raw),
        "encoding": "utf-8 (errors=replace)",
        "extension": ext,
    }


# ── Archive listing ──────────────────────────────────────────────────────────

_ZIP_EXTS = {".zip", ".epub", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
_TAR_EXTS = {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}
_SEVENZ_EXTS = {".7z"}


def _archive_format(p: Path) -> str | None:
    name_lower = p.name.lower()
    if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz"):
        return "tar.gz"
    if name_lower.endswith(".tar.bz2") or name_lower.endswith(".tbz2"):
        return "tar.bz2"
    if name_lower.endswith(".tar.xz") or name_lower.endswith(".txz"):
        return "tar.xz"
    ext = p.suffix.lower()
    if ext in _ZIP_EXTS:
        return "zip"
    if ext in _TAR_EXTS:
        return "tar"
    if ext in _SEVENZ_EXTS:
        return "7z"
    return None


def _list_zip_sync(p: Path) -> dict:
    entries: list[dict] = []
    total_uncompressed = 0
    truncated = False
    with zipfile.ZipFile(str(p), "r") as zf:
        infos = zf.infolist()
        for idx, info in enumerate(infos):
            if idx >= _ARCHIVE_LISTING_MAX_ENTRIES:
                truncated = True
                break
            mtime_iso = None
            try:
                dt = datetime(*info.date_time, tzinfo=timezone.utc)
                mtime_iso = dt.isoformat()
            except (ValueError, TypeError):
                pass
            total_uncompressed += info.file_size
            entries.append({
                "name": info.filename,
                "size_bytes": info.file_size,
                "compressed_bytes": info.compress_size,
                "is_dir": info.is_dir(),
                "modified_iso": mtime_iso,
            })
    return {
        "format": "zip",
        "entry_count": len(entries),
        "uncompressed_total_bytes": total_uncompressed,
        "truncated": truncated,
        "entries": entries,
    }


def _list_tar_sync(p: Path) -> dict:
    entries: list[dict] = []
    total_uncompressed = 0
    truncated = False
    # `r:*` auto-detects gzip / bzip2 / xz / plain by the first bytes.
    with tarfile.open(str(p), "r:*") as tf:
        for idx, member in enumerate(tf):
            if idx >= _ARCHIVE_LISTING_MAX_ENTRIES:
                truncated = True
                break
            mtime_iso = None
            try:
                mtime_iso = datetime.fromtimestamp(
                    member.mtime, tz=timezone.utc,
                ).isoformat()
            except (OSError, ValueError, OverflowError):
                pass
            total_uncompressed += member.size
            entries.append({
                "name": member.name,
                "size_bytes": member.size,
                "compressed_bytes": None,
                "is_dir": member.isdir(),
                "modified_iso": mtime_iso,
            })
    return {
        "format": "tar",
        "entry_count": len(entries),
        "uncompressed_total_bytes": total_uncompressed,
        "truncated": truncated,
        "entries": entries,
    }


def _list_seven_z_sync(p: Path) -> dict:
    """Use the `/usr/bin/7z l -slt` listing command. Each entry block
    is separated by a blank line; we parse `Path =`, `Size =`,
    `Modified =`, `Folder =`."""
    import subprocess
    proc = subprocess.run(
        ["/usr/bin/7z", "l", "-slt", "-y", str(p)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"7z list failed (rc={proc.returncode}): {proc.stderr[:500]}"
        )

    entries: list[dict] = []
    total_uncompressed = 0
    truncated = False
    block: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            if "Path" in block:
                if len(entries) >= _ARCHIVE_LISTING_MAX_ENTRIES:
                    truncated = True
                    break
                size = 0
                try:
                    size = int(block.get("Size", "0") or 0)
                except (TypeError, ValueError):
                    size = 0
                total_uncompressed += size
                is_dir = (block.get("Folder", "").lower() == "+")
                mtime_iso = None
                modified = block.get("Modified", "").strip()
                if modified:
                    try:
                        dt = datetime.fromisoformat(modified.replace(" ", "T"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        mtime_iso = dt.isoformat()
                    except ValueError:
                        pass
                entries.append({
                    "name": block.get("Path", ""),
                    "size_bytes": size,
                    "compressed_bytes": None,
                    "is_dir": is_dir,
                    "modified_iso": mtime_iso,
                })
            block = {}
            continue
        if " = " in line:
            key, _, val = line.partition(" = ")
            block[key.strip()] = val
    # Final block, if no trailing blank line
    if "Path" in block and not truncated and len(entries) < _ARCHIVE_LISTING_MAX_ENTRIES:
        try:
            size = int(block.get("Size", "0") or 0)
        except (TypeError, ValueError):
            size = 0
        total_uncompressed += size
        is_dir = (block.get("Folder", "").lower() == "+")
        entries.append({
            "name": block.get("Path", ""),
            "size_bytes": size,
            "compressed_bytes": None,
            "is_dir": is_dir,
            "modified_iso": None,
        })
    return {
        "format": "7z",
        "entry_count": len(entries),
        "uncompressed_total_bytes": total_uncompressed,
        "truncated": truncated,
        "entries": entries,
    }


@router.get("/archive-listing")
async def get_preview_archive_listing(
    path: str = Query(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return a read-only listing of an archive's entries (capped at
    500). Supports zip, tar (auto-detected gz/bz2/xz), and 7z (via
    the system 7z binary).

    For Office documents (.docx/.xlsx/etc.) which are technically
    zip files, this endpoint surfaces their internal layout — useful
    when a converter behaves oddly on a malformed file."""
    p = _normalize_path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    fmt = _archive_format(p)
    if fmt is None:
        raise HTTPException(
            status_code=400,
            detail="archive listing not available for this file type",
        )

    try:
        if fmt == "zip":
            result = await asyncio.to_thread(_list_zip_sync, p)
        elif fmt == "tar" or fmt.startswith("tar."):
            result = await asyncio.to_thread(_list_tar_sync, p)
        elif fmt == "7z":
            result = await asyncio.to_thread(_list_seven_z_sync, p)
        else:
            raise HTTPException(
                status_code=400, detail=f"unsupported archive format {fmt}",
            )
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise HTTPException(
            status_code=422, detail=f"archive is corrupt or unreadable: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500, detail=str(exc),
        ) from exc

    log.info(
        "preview.archive_listing",
        user=user.email,
        path=str(p),
        format=result.get("format"),
        entry_count=result.get("entry_count"),
        truncated=result.get("truncated"),
    )
    return {**result, "path": str(p)}


@router.get("/markdown-output")
async def get_preview_markdown_output(
    path: str = Query(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return the converted Markdown for `path` if a successful
    conversion exists. 404 if no successful bulk_files row was
    found, the output_path field is empty, or the output file is
    missing on disk.

    This lets the preview page show inline rendered Markdown for
    Office docs without bouncing the user to viewer.html. The full
    viewer.html experience is still recommended via a link in the
    actions panel — that page has TOC, page-up/down, etc.
    """
    p = _normalize_path(path)
    bulk_file = await _lookup_latest_bulk_file(str(p))
    if not bulk_file or bulk_file.get("status") != "success":
        raise HTTPException(
            status_code=404,
            detail="no successful conversion exists for this file",
        )
    output_path = bulk_file.get("output_path")
    if not output_path:
        raise HTTPException(
            status_code=404,
            detail="conversion succeeded but output_path is empty (data drift?)",
        )

    out = Path(output_path)
    if not is_path_under_allowed_root(out):
        log.warning(
            "preview.markdown_output_outside_allowed_roots",
            output_path=output_path, source_path=str(p),
        )
        raise HTTPException(
            status_code=400,
            detail="converted output is outside the allowed mount roots",
        )
    if not out.exists() or not out.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"converted output is missing on disk: {output_path}",
        )

    def _read() -> str:
        with open(out, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    markdown = await asyncio.to_thread(_read)
    log.info(
        "preview.markdown_output",
        user=user.email,
        source_path=str(p),
        output_path=output_path,
        bytes_returned=len(markdown.encode("utf-8")),
    )
    return {
        "source_path": str(p),
        "output_path": output_path,
        "converted_at": bulk_file.get("converted_at"),
        "markdown": markdown,
    }


# ── Force-action endpoint (v0.32.0) ──────────────────────────────────────────
#
# The preview-page "Process this file" button posts here. We pick the
# action by extension via `pick_action_for_path`, prepare the right DB
# row (bulk_files for transcribe/convert, analysis_queue for analyze),
# kick off the work in a BackgroundTask, and record per-path progress
# in `_FORCE_ACTION_STATE` for the polling status endpoint.
#
# Concurrency: a per-path entry serializes status. If you click the
# button twice on the same file, the second call returns 409 unless
# the prior run is finished (success/failed/idle).

# Lifecycle of a force-action progress entry. Each phase is what gets
# returned in the status endpoint's `phase` field. Frontend uses this
# to render a stepper / human-readable label.
_FA_STATE_QUEUED = "queued"          # Background task scheduled, work hasn't begun
_FA_STATE_PREPARING = "preparing"    # Writing bulk_files / analysis_queue row
_FA_STATE_RUNNING = "running"        # Engine is converting / transcribing / analyzing
_FA_STATE_INDEXING = "indexing"      # Post-conversion: registering output + reindex
_FA_STATE_SUCCESS = "success"
_FA_STATE_FAILED = "failed"

# In-memory progress dict. Keyed on resolved source_path. Process-local;
# resets on container restart. Capped to prevent unbounded growth in
# rare "operator clicks 10000 times" scenarios.
_FORCE_ACTION_STATE: dict[str, dict] = {}
_FORCE_ACTION_STATE_LOCK = asyncio.Lock()
_FORCE_ACTION_STATE_MAX = 1000


def _fa_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fa_record(path: str, **fields) -> None:
    """Update or insert the progress record for `path`. Called from
    the background task at each phase transition. Caller should hold
    no lock — this function takes its own."""
    cur = _FORCE_ACTION_STATE.get(path) or {}
    cur.update(fields)
    cur["updated_at"] = _fa_now_iso()
    _FORCE_ACTION_STATE[path] = cur

    # Trim oldest entries if we hit the cap. LRU by `updated_at`.
    if len(_FORCE_ACTION_STATE) > _FORCE_ACTION_STATE_MAX:
        oldest = sorted(
            _FORCE_ACTION_STATE.items(),
            key=lambda kv: kv[1].get("updated_at", ""),
        )
        for k, _ in oldest[: len(_FORCE_ACTION_STATE) - _FORCE_ACTION_STATE_MAX]:
            _FORCE_ACTION_STATE.pop(k, None)


class ForceActionRequest(BaseModel):
    path: str = Field(..., description="Absolute container path to force-process")


async def _force_action_run_convert_or_transcribe(
    path: Path, action: str, user_email: str,
) -> None:
    """Background runner for `transcribe` and `convert` actions.

    Both verbs share the same conversion machinery — the converter
    routes by extension internally (audio/video → Whisper, office →
    handler, etc.). This function:

      1. Upserts a bulk_files row (status='pending') so the converter
         has a target for its UPDATE.
      2. Looks up the actual row id (upsert returns a synthetic id on
         conflict that doesn't match the persisted row).
      3. Calls _convert_one_pending_file() — same path the v0.31.6
         "Convert Selected" feature uses, so we get all the same
         routing, output mapping, write-guard, indexing, etc.
      4. Records phase transitions so the polling endpoint can show
         progress to the operator.
    """
    from api.routes.pipeline import _convert_one_pending_file
    from core.db.bulk import upsert_bulk_file

    path_str = str(path)
    try:
        st = path.stat()
    except OSError as exc:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=f"file not accessible: {exc}",
            finished_at=_fa_now_iso(),
        )
        return

    _fa_record(path_str, state=_FA_STATE_PREPARING, phase=_FA_STATE_PREPARING)
    try:
        await upsert_bulk_file(
            job_id=f"force-{action}",
            source_path=path_str,
            file_ext=path.suffix.lower(),
            file_size_bytes=st.st_size,
            source_mtime=st.st_mtime,
        )
    except Exception as exc:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=f"upsert_bulk_file failed: {type(exc).__name__}: {exc}",
            finished_at=_fa_now_iso(),
        )
        log.error(
            "preview.force_action.upsert_failed",
            path=path_str, action=action,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    # The upsert returns a synthetic uuid on conflict that doesn't
    # match the persisted id. Fetch the real row instead.
    row = await db_fetch_one(
        "SELECT id, source_path, source_mtime, status, job_id, file_ext "
        "FROM bulk_files WHERE source_path = ?",
        (path_str,),
    )
    if not row:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error="bulk_files row vanished after upsert",
            finished_at=_fa_now_iso(),
        )
        return

    file_dict = dict(row)
    _fa_record(path_str, state=_FA_STATE_RUNNING, phase=_FA_STATE_RUNNING)
    try:
        await _convert_one_pending_file(file_dict, user_email)
    except Exception as exc:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=f"{type(exc).__name__}: {exc}",
            finished_at=_fa_now_iso(),
        )
        log.error(
            "preview.force_action.convert_exception",
            path=path_str, action=action,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    # Re-fetch to determine final status — _convert_one_pending_file
    # writes back to bulk_files but doesn't return the result.
    final = await db_fetch_one(
        "SELECT status, output_path, error_msg FROM bulk_files WHERE source_path = ?",
        (path_str,),
    )
    final_status = (final or {}).get("status")
    output_path = (final or {}).get("output_path")
    err = (final or {}).get("error_msg")

    if final_status == "converted":
        _fa_record(
            path_str, state=_FA_STATE_SUCCESS, phase=_FA_STATE_SUCCESS,
            output_path=output_path, error=None,
            finished_at=_fa_now_iso(),
        )
        log.info(
            "preview.force_action.converted",
            path=path_str, action=action, output=output_path,
        )
    else:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=err or f"final status: {final_status}",
            finished_at=_fa_now_iso(),
        )
        log.warning(
            "preview.force_action.failed",
            path=path_str, action=action,
            final_status=final_status, error=err,
        )


async def _force_action_run_analyze(path: Path, user_email: str) -> None:
    """Background runner for the `analyze` action. Enqueues the file
    in analysis_queue (or re-uses an existing pending row) and then
    kicks `run_analysis_drain` so we don't have to wait up to 5 min
    for the next scheduled tick."""
    from core.analysis_worker import run_analysis_drain
    from core.db.analysis import enqueue_for_analysis

    path_str = str(path)
    _fa_record(path_str, state=_FA_STATE_PREPARING, phase=_FA_STATE_PREPARING)

    try:
        entry_id = await enqueue_for_analysis(
            source_path=path_str,
            content_hash=None,
            job_id="force-analyze",
            scan_run_id="force-analyze",
            file_category="image",
        )
    except Exception as exc:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=f"enqueue_for_analysis failed: {type(exc).__name__}: {exc}",
            finished_at=_fa_now_iso(),
        )
        return

    _fa_record(
        path_str, state=_FA_STATE_RUNNING, phase=_FA_STATE_RUNNING,
        analysis_queue_id=entry_id,
    )
    try:
        # Force one drain immediately. Caps + circuit breakers inside
        # run_analysis_drain protect against thundering herds.
        await run_analysis_drain()
    except Exception as exc:
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=f"analysis drain raised: {type(exc).__name__}: {exc}",
            finished_at=_fa_now_iso(),
        )
        log.error(
            "preview.force_action.analyze_exception",
            path=path_str, error=f"{type(exc).__name__}: {exc}",
        )
        return

    # Re-check the row: drain may have completed it, or it may still
    # be 'batched' if the LLM call is in flight.
    row = await db_fetch_one(
        "SELECT status, error, description FROM analysis_queue WHERE source_path = ?",
        (path_str,),
    )
    status = (row or {}).get("status")
    if status == "completed":
        _fa_record(
            path_str, state=_FA_STATE_SUCCESS, phase=_FA_STATE_SUCCESS,
            error=None, finished_at=_fa_now_iso(),
        )
    elif status == "failed":
        _fa_record(
            path_str, state=_FA_STATE_FAILED, phase=_FA_STATE_FAILED,
            error=(row or {}).get("error") or "analysis failed",
            finished_at=_fa_now_iso(),
        )
    else:
        # Still pending/batched — drain probably saw the row but the
        # provider call is still in flight, or the worker batched it
        # for the next cycle. Tell the operator honestly.
        _fa_record(
            path_str, state=_FA_STATE_RUNNING, phase=_FA_STATE_RUNNING,
            note=f"queued (status={status}); will resolve on the next worker tick",
        )


@router.post("/force-action")
async def force_action(
    body: ForceActionRequest,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Force-process a single file by absolute container path.

    Picks the action by extension via `pick_action_for_path`:
      - audio/video  → transcribe (Whisper)
      - office/pdf/text/archive → convert
      - image → analyze (LLM vision)
      - unknown → 400

    Rejects re-entrant clicks: if a prior run for this path is still
    queued/preparing/running, returns 409. Use the status endpoint to
    poll progress.
    """
    p = _normalize_path(body.path)
    if not p.exists() or not p.is_file():
        raise HTTPException(
            status_code=404,
            detail="file not found on disk",
        )

    action = pick_action_for_path(p)
    if action == ACTION_NONE:
        raise HTTPException(
            status_code=400,
            detail=f"no force-action available for extension '{p.suffix}'",
        )

    path_str = str(p)
    async with _FORCE_ACTION_STATE_LOCK:
        existing = _FORCE_ACTION_STATE.get(path_str)
        if existing and existing.get("state") in (
            _FA_STATE_QUEUED, _FA_STATE_PREPARING, _FA_STATE_RUNNING,
            _FA_STATE_INDEXING,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "msg": "force-action already in flight for this file",
                    "current": existing,
                },
            )
        _fa_record(
            path_str,
            state=_FA_STATE_QUEUED,
            phase=_FA_STATE_QUEUED,
            action=action,
            started_at=_fa_now_iso(),
            finished_at=None,
            error=None,
            output_path=None,
            user=user.email,
        )

    if action == ACTION_ANALYZE:
        background_tasks.add_task(_force_action_run_analyze, p, user.email)
    else:
        # transcribe and convert share the same engine path.
        background_tasks.add_task(
            _force_action_run_convert_or_transcribe, p, action, user.email,
        )

    log.info(
        "preview.force_action.scheduled",
        user=user.email, path=path_str, action=action,
    )
    return {
        "path": path_str,
        "action": action,
        "state": _FA_STATE_QUEUED,
        "message": f"Scheduled {action} for {p.name}",
    }


@router.get("/force-action-status")
async def force_action_status(
    path: str = Query(..., description="Absolute container path to query"),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Return the current force-action progress for `path`.

    Returns `state='idle'` if no action has been scheduled in this
    process's lifetime. Otherwise returns the latest progress record
    (state, phase, started_at, updated_at, finished_at, error,
    output_path, action, elapsed_ms).
    """
    p = _normalize_path(path)
    path_str = str(p)
    rec = _FORCE_ACTION_STATE.get(path_str)
    if not rec:
        return {
            "path": path_str,
            "state": "idle",
            "phase": "idle",
            "action": pick_action_for_path(p),
        }

    # Compute elapsed_ms client-side-friendly. If finished, freeze at
    # finished_at - started_at; otherwise it's now - started_at.
    started_at = rec.get("started_at")
    finished_at = rec.get("finished_at")
    elapsed_ms: int | None = None
    try:
        if started_at:
            t_start = datetime.fromisoformat(started_at)
            t_end = (
                datetime.fromisoformat(finished_at)
                if finished_at else datetime.now(timezone.utc)
            )
            elapsed_ms = int((t_end - t_start).total_seconds() * 1000)
    except (TypeError, ValueError):
        pass

    return {
        "path": path_str,
        **rec,
        "elapsed_ms": elapsed_ms,
    }


# ── Related-files search (v0.32.0) ──────────────────────────────────────────
#
# The preview-page sidebar's search panel and auto-related card both
# call this endpoint. Two modes:
#   - keyword: Meilisearch full-text on the documents index
#   - semantic: Qdrant vector search, mapped back to source_path via
#               a Meili lookup keyed on the doc_id
#
# When `q` is empty, the query is derived from the file (transcript
# excerpt → analysis description → filename + parent dir tokens) so
# auto-population can work without the operator typing anything.

# Cap the derived-query length sent to the search backends. Vector
# embeddings tolerate longer inputs but Meili is happiest with short,
# bag-of-terms queries; 1000 chars is more than enough for either.
_RELATED_QUERY_MAX_CHARS = 1000

# Cap the result set. The sidebar lists are short by design; a longer
# list belongs on /search.html.
_RELATED_LIMIT_DEFAULT = 10
_RELATED_LIMIT_MAX = 25


async def _read_markdown_excerpt(out_path: str, max_chars: int) -> str:
    """Read the first `max_chars` of a converted-Markdown file. Used
    to derive a similarity query from a file's own transcript."""
    out = Path(out_path)
    if not out.exists() or not out.is_file():
        return ""

    def _read() -> str:
        with open(out, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)

    try:
        return await asyncio.to_thread(_read)
    except OSError:
        return ""


async def _derive_related_query(p: Path) -> str:
    """Build a search query for finding files similar to `p`.

    Order of preference (richest signal first):
      1. Converted Markdown excerpt — works for audio/video transcripts
         and Office docs; the actual content is the strongest similarity
         signal.
      2. Analysis description — for images, this is the LLM-generated
         summary which captures the semantic content of the picture.
      3. Filename stem + parent directory name — better than nothing
         for files that haven't been processed yet.
    """
    bulk_file = await _lookup_latest_bulk_file(str(p))
    if bulk_file and bulk_file.get("status") == "success":
        out_path = bulk_file.get("output_path")
        if out_path:
            text = await _read_markdown_excerpt(out_path, _RELATED_QUERY_MAX_CHARS)
            if text.strip():
                return text.strip()

    analysis = await _lookup_analysis_row(str(p))
    if analysis and analysis.get("description"):
        return str(analysis["description"]).strip()

    parent_name = p.parent.name or ""
    fallback = f"{p.stem} {parent_name}".strip() or p.name
    return fallback


@router.get("/related")
async def get_preview_related(
    path: str = Query(..., description="Absolute container path"),
    mode: str = Query("semantic", pattern="^(keyword|semantic)$"),
    q: str | None = Query(
        None,
        description="Override query text. If omitted, the query is "
                    "derived from the file (transcript / description / name).",
    ),
    limit: int = Query(
        _RELATED_LIMIT_DEFAULT,
        ge=1, le=_RELATED_LIMIT_MAX,
    ),
    user: AuthenticatedUser = Depends(require_role(UserRole.OPERATOR)),
) -> dict:
    """Find files similar to `path` via Meili (keyword) or Qdrant (semantic).

    Returns the list of hits with the current file filtered out so we
    don't suggest "this very file" as a related result. When the
    underlying backend is unavailable, returns an empty `results` array
    plus a `warning` field so the frontend can show a graceful message
    instead of an error.

    Cost note: this endpoint deliberately does NOT call the AI Assist
    synthesis pipeline — that would auto-fire LLM calls on every
    preview-page open. The frontend exposes "AI Assist" as a deep-link
    to /search.html?ai=1 instead, so token spend is operator-initiated.
    """
    p = _normalize_path(path)
    path_str = str(p)

    query = (q or "").strip()
    derived = False
    if not query:
        query = await _derive_related_query(p)
        derived = True
    if not query:
        return {
            "path": path_str, "mode": mode, "query_used": "",
            "derived": derived, "results": [],
        }

    query = query[: _RELATED_QUERY_MAX_CHARS]
    results: list[dict] = []
    warning: str | None = None

    if mode == "keyword":
        from core.search_client import get_meili_client
        client = get_meili_client()
        if not await client.health_check():
            warning = "Search index is unavailable."
        else:
            meili_resp = await client.search(
                "documents", query,
                {
                    "limit": limit + 1,  # +1 for self-filter
                    "attributesToRetrieve": [
                        "id", "source_path", "relative_path", "title",
                        "source_format", "file_size_bytes", "modified_at",
                    ],
                },
            )
            for hit in meili_resp.get("hits", []):
                hit_path = hit.get("source_path") or hit.get("relative_path")
                if not hit_path or hit_path == path_str:
                    continue
                results.append({
                    "path": hit_path,
                    "name": hit.get("title") or Path(hit_path).name,
                    "score": None,
                    "source_format": hit.get("source_format"),
                    "size_bytes": hit.get("file_size_bytes"),
                    "modified_at": hit.get("modified_at"),
                    "doc_id": hit.get("id"),
                })
                if len(results) >= limit:
                    break
    else:  # semantic
        try:
            from core.vector.index_manager import get_vector_indexer
        except ImportError:
            warning = "Vector backend module not present."
            get_vector_indexer = None  # type: ignore[assignment]
        if get_vector_indexer is not None:
            try:
                vec = await get_vector_indexer()
            except Exception as exc:  # noqa: BLE001
                vec = None
                warning = f"Vector backend init failed: {exc}"
            if vec is None and not warning:
                warning = "Vector backend is offline (Qdrant unreachable?)."
            if vec is not None:
                try:
                    hits = await vec.search(query=query, limit=limit + 1)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "preview.related.semantic_failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    warning = f"Semantic search failed: {exc}"
                    hits = []

                # vec.search() returns dicts with `source_path` already
                # populated — Qdrant payload includes it. No Meili
                # roundtrip needed.
                seen_paths: set[str] = set()
                for hit in hits:
                    hit_path = hit.get("source_path")
                    if not hit_path or hit_path == path_str or hit_path in seen_paths:
                        continue
                    seen_paths.add(hit_path)
                    results.append({
                        "path": hit_path,
                        "name": hit.get("title") or Path(hit_path).name,
                        "score": hit.get("score"),
                        "source_format": hit.get("source_format"),
                        "size_bytes": None,
                        "modified_at": None,
                        "doc_id": hit.get("doc_id"),
                        "snippet": (hit.get("chunk_text") or "")[:200],
                    })
                    if len(results) >= limit:
                        break

    log.info(
        "preview.related",
        user=user.email,
        path=path_str,
        mode=mode,
        derived=derived,
        query_len=len(query),
        result_count=len(results),
        warning=warning,
    )

    return {
        "path": path_str,
        "mode": mode,
        "query_used": query,
        "derived": derived,
        "results": results,
        "warning": warning,
    }
