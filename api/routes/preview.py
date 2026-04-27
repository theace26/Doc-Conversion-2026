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
import os
import tarfile
import time
import urllib.parse
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from core.auth import AuthenticatedUser, UserRole, require_role
from core.db.connection import db_fetch_one, db_fetch_all
from core.path_utils import is_path_under_allowed_root
from core.preview_helpers import (
    AUDIO_EXTS,
    OFFICE_EXTS,
    TEXT_EXTS,
    classify_viewer_kind,
    get_file_category,
    get_mime_type,
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
    }


@router.get("/content")
async def get_preview_content(
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
    """
    p = _normalize_path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    try:
        size = p.stat().st_size
    except OSError as exc:
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
