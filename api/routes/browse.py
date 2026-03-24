"""
Directory browser API — lists folders (and optionally files) under allowed roots.

GET /api/browse?path=/host/c&show_files=false

Security: Only /host/* and /mnt/output-repo are browsable. Path traversal
and null bytes are rejected before any filesystem access.
"""

import asyncio
import os
import stat as stat_module
from pathlib import Path, PurePosixPath

import structlog
from fastapi import APIRouter, HTTPException, Query

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/browse", tags=["browse"])

ALLOWED_BROWSE_ROOTS = ["/host", "/mnt/output-repo"]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_mounted_drives() -> list[str]:
    """Return list of drive letters from MOUNTED_DRIVES env var (e.g. ['c','d'])."""
    raw = os.getenv("MOUNTED_DRIVES", "")
    if not raw:
        return []
    return [letter.strip().lower() for letter in raw.split(",") if letter.strip()]


def _validate_browse_path(path: str) -> Path:
    """
    Validate and resolve a browse path. Raises HTTPException on violations.

    Rules:
      1. No null bytes
      2. Resolve to absolute path (no .. traversal)
      3. Must be under one of ALLOWED_BROWSE_ROOTS, or exactly equal to one
    """
    if "\x00" in path:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "message": "Null bytes not allowed in path"},
        )

    # Normalize: remove trailing slashes, collapse double slashes
    cleaned = str(PurePosixPath(path))

    # Check for .. components before resolving
    if ".." in cleaned.split("/"):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "message": "Path traversal not allowed"},
        )

    resolved = Path(cleaned).resolve()
    resolved_str = str(resolved).replace("\\", "/")

    # Must start with one of the allowed roots
    if not any(
        resolved_str == root or resolved_str.startswith(root + "/")
        for root in ALLOWED_BROWSE_ROOTS
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "path_not_allowed",
                "message": "Browsing is restricted to mounted drives (/host/) "
                           "and the output repo (/mnt/output-repo)",
            },
        )

    return resolved


def _build_drives_list() -> list[dict]:
    """Build the drives array showing which drive letters are mounted."""
    letters = _get_mounted_drives()
    drives = []
    for letter in letters:
        host_path = Path(f"/host/{letter}")
        mounted = False
        try:
            mounted = host_path.is_dir() and os.access(str(host_path), os.R_OK)
        except OSError:
            pass
        drives.append({
            "name": f"{letter.upper()}:",
            "path": f"/host/{letter}",
            "mounted": mounted,
        })
    return drives


def _safe_item_count(entry_path: Path) -> int | None:
    """Count immediate children of a directory. Returns None on any error."""
    try:
        return len(os.listdir(entry_path))
    except (PermissionError, OSError):
        return None


def _safe_is_symlink_escape(entry_path: Path) -> bool:
    """Check if a symlink resolves outside allowed roots."""
    if not entry_path.is_symlink():
        return False
    try:
        target = entry_path.resolve()
        target_str = str(target).replace("\\", "/")
        return not any(
            target_str == root or target_str.startswith(root + "/")
            for root in ALLOWED_BROWSE_ROOTS
        )
    except OSError:
        return True  # Can't resolve — treat as escape


def _list_directory(path: Path, show_files: bool) -> list[dict]:
    """List directory entries, sorted: dirs first (alpha), then files (alpha)."""
    dirs = []
    files = []

    try:
        entries = os.listdir(path)
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "not_readable",
                "path": str(path).replace("\\", "/"),
                "message": "Permission denied",
            },
        )

    for name in entries:
        entry_path = path / name

        # Skip symlinks that escape allowed roots
        if _safe_is_symlink_escape(entry_path):
            continue

        # Use lstat to avoid following symlinks for type detection
        try:
            stat = os.lstat(entry_path)
        except (PermissionError, OSError):
            continue

        is_dir = stat_module.S_ISDIR(stat.st_mode)
        if not is_dir and not show_files:
            continue

        readable = True
        item_count = None
        try:
            if is_dir:
                os.listdir(entry_path)
                item_count = _safe_item_count(entry_path)
        except (PermissionError, OSError):
            readable = False

        entry = {
            "name": name,
            "path": str(entry_path).replace("\\", "/"),
            "type": "directory" if is_dir else "file",
            "readable": readable,
            "item_count": item_count if is_dir else None,
        }

        if is_dir:
            dirs.append(entry)
        else:
            files.append(entry)

    # Sort case-insensitive
    dirs.sort(key=lambda e: e["name"].lower())
    files.sort(key=lambda e: e["name"].lower())
    return dirs + files


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("")
async def browse_directory(
    path: str = Query(default="/host", description="Container-side path to list"),
    show_files: bool = Query(default=False, description="Include files in listing"),
):
    """Browse directories under allowed roots (/host/*, /mnt/output-repo)."""
    resolved = _validate_browse_path(path)

    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "path": path},
        )

    entries = await asyncio.to_thread(_list_directory, resolved, show_files)

    # Compute parent path
    resolved_str = str(resolved).replace("\\", "/")
    parent_str = str(resolved.parent).replace("\\", "/")

    # Determine if we're at a browse root
    is_root = resolved_str in ALLOWED_BROWSE_ROOTS

    # Parent: go up unless at root. At /host, parent is null.
    parent = None
    if not is_root:
        # If parent is above an allowed root, set parent to the root
        if any(
            parent_str == root or parent_str.startswith(root + "/")
            for root in ALLOWED_BROWSE_ROOTS
        ):
            parent = parent_str
        else:
            # Going up from /host/c → /host (still an allowed root)
            for root in ALLOWED_BROWSE_ROOTS:
                if resolved_str.startswith(root + "/"):
                    parent = root
                    break

    drives = _build_drives_list()

    return {
        "path": resolved_str,
        "parent": parent,
        "is_root": is_root,
        "entries": entries,
        "drives": drives,
    }
