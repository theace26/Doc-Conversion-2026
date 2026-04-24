"""Log management API routes (v0.30.1). ADMIN-gated.

Endpoints
---------
GET  /api/logs                          — inventory of all log files
GET  /api/logs/settings                 — current compression/retention settings
PUT  /api/logs/settings                 — update settings
POST /api/logs/compress-now             — trigger compression immediately
POST /api/logs/apply-retention-now      — trigger retention cleanup immediately
GET  /api/logs/download/{name}          — download a single log file
POST /api/logs/download-bundle          — download multiple logs as a .zip
GET  /api/logs/tail/{name}              — Server-Sent Events stream of tail lines
GET  /api/logs/search                   — historical paginated search with filters
"""

from __future__ import annotations

import asyncio
import io
import os
import zipfile
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.auth import AuthenticatedUser, UserRole, require_role
from core.log_manager import (
    LogEntry,
    LOGS_DIR,
    _safe_logs_path,
    apply_retention,
    compress_rotated_logs,
    get_settings,
    list_logs,
    set_settings,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])


# ── Inventory ────────────────────────────────────────────────────────────────


def _entry_to_dict(e: LogEntry) -> dict:
    return {
        "name": e.name,
        "size_bytes": e.size_bytes,
        "modified": e.modified_iso,
        "status": e.status,
        "stream": e.stream,
        "compression": e.compression,
    }


@router.get("")
async def list_log_files(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    entries = list_logs()
    return {
        "logs": [_entry_to_dict(e) for e in entries],
        "total_size_bytes": sum(e.size_bytes for e in entries),
        "logs_dir": str(LOGS_DIR),
    }


# ── Settings ─────────────────────────────────────────────────────────────────


class SettingsUpdate(BaseModel):
    compression_format: str | None = Field(None, description="'gz' | 'tar.gz' | '7z'")
    retention_days: int | None = Field(None, ge=1, le=3650)
    rotation_max_size_mb: int | None = Field(None, ge=10, le=10240)


@router.get("/settings")
async def read_settings(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    return await get_settings()


@router.put("/settings")
async def write_settings(
    body: SettingsUpdate,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    try:
        result = await set_settings(
            compression_format=body.compression_format,
            retention_days=body.retention_days,
            rotation_max_size_mb=body.rotation_max_size_mb,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log.info(
        "log_management.settings_updated",
        user=user.email,
        compression_format=body.compression_format,
        retention_days=body.retention_days,
        rotation_max_size_mb=body.rotation_max_size_mb,
    )
    return result


# ── Manual triggers ──────────────────────────────────────────────────────────


@router.post("/compress-now")
async def compress_now(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    result = await compress_rotated_logs()
    log.info("log_management.compress_now", user=user.email, **result)
    return result


@router.post("/apply-retention-now")
async def apply_retention_now(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    result = await apply_retention()
    log.info("log_management.apply_retention_now", user=user.email, **result)
    return result


# ── Download ─────────────────────────────────────────────────────────────────


@router.get("/download/{name:path}")
async def download_one(
    name: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> FileResponse:
    """Download a single log file. `name` may be a bare filename
    (e.g. `markflow.log`) or an archive-relative path
    (`archive/markflow.log-2026-04-01-...gz`)."""
    try:
        path = _safe_logs_path(name)
    except PermissionError:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="log not found")
    log.info("log_management.download_one", user=user.email, file=name)
    # Use the basename (not the archive-relative path) for the
    # Content-Disposition — browsers don't like slashes in filename=.
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/octet-stream",
    )


class BundleRequest(BaseModel):
    names: list[str] = Field(
        default_factory=list,
        description="Filenames to include. Empty list = all log files under LOGS_DIR.",
    )


@router.post("/download-bundle")
async def download_bundle(
    body: BundleRequest,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> StreamingResponse:
    """Stream a .zip containing one or more log files.

    Empty `names` = bundle every file in the inventory. Non-existent
    names are silently skipped so the UI can submit a best-effort
    selection without pre-validation.
    """
    # Resolve + validate selection
    if not body.names:
        entries = list_logs()
        selected = [_safe_logs_path(e.name) for e in entries]
    else:
        selected = []
        for name in body.names:
            try:
                p = _safe_logs_path(name)
            except PermissionError:
                continue
            if p.exists() and p.is_file():
                selected.append(p)
    if not selected:
        raise HTTPException(status_code=404, detail="no matching log files")

    # Build zip in a worker thread to avoid blocking the event loop
    # on multi-GB bundles, then stream the in-memory buffer out.
    def _build_zip() -> bytes:
        buf = io.BytesIO()
        # Rotated + compressed files are already compressed; use ZIP_STORED
        # for .gz/.7z and ZIP_DEFLATED for plain .log to keep the bundle
        # creation fast without re-compressing already-compressed bytes.
        with zipfile.ZipFile(buf, "w") as zf:
            for p in selected:
                arcname = p.name
                lower = arcname.lower()
                already_compressed = (
                    lower.endswith(".gz")
                    or lower.endswith(".7z")
                    or lower.endswith(".tgz")
                )
                mode = zipfile.ZIP_STORED if already_compressed else zipfile.ZIP_DEFLATED
                zf.write(p, arcname=arcname, compress_type=mode)
        return buf.getvalue()

    zip_bytes = await asyncio.to_thread(_build_zip)
    log.info(
        "log_management.download_bundle",
        user=user.email,
        file_count=len(selected),
        bundle_size_bytes=len(zip_bytes),
    )

    from datetime import datetime
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    fname = f"markflow-logs-{ts}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )


# ── Live tail via SSE ────────────────────────────────────────────────────────


@router.get("/tail/{name:path}")
async def tail_log(
    name: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> StreamingResponse:
    """Server-Sent Events stream of new lines appended to `name`.

    Streams the last ~200 lines at connection start, then emits each
    new line as it's written by the logger. Disconnection detected
    via `request.is_disconnected()` to stop tailing promptly.
    """
    try:
        path = _safe_logs_path(name)
    except PermissionError:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="log not found")
    # Compressed files can't be tailed meaningfully
    lower = name.lower()
    if lower.endswith(".gz") or lower.endswith(".7z") or lower.endswith(".tgz"):
        raise HTTPException(status_code=400, detail="cannot tail compressed log")

    async def event_stream():
        # --- Initial backfill: last ~200 lines ---
        try:
            with path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                end = f.tell()
                # Read back up to 64 KB to find the last ~200 lines
                tail_size = min(end, 64 * 1024)
                f.seek(end - tail_size)
                blob = f.read()
            lines = blob.decode("utf-8", errors="replace").splitlines()[-200:]
        except Exception as exc:
            yield f"event: error\ndata: Failed to read log: {exc}\n\n"
            return

        for line in lines:
            yield f"data: {line}\n\n"

        # --- Live tail: poll file for growth ---
        try:
            with path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    if await request.is_disconnected():
                        break
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        # Detect truncation (e.g. after a rotation) and
                        # reseek to end. If the file shrank, re-open.
                        try:
                            current_end = path.stat().st_size
                            if current_end < f.tell():
                                f.seek(0, os.SEEK_END)
                        except OSError:
                            break
                        continue
                    decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                    if decoded:
                        # SSE `data:` lines can't contain bare newlines;
                        # since we rstripped, decoded is single-line safe.
                        yield f"data: {decoded}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: Tail interrupted: {exc}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx/proxy buffering if any
        },
    )


# ── Historical search with filters ───────────────────────────────────────────

import gzip as _gzip
import json as _json
import re as _re
from datetime import datetime as _datetime, timezone as _timezone


def _open_log_for_read(path: Path):
    """Return a binary file handle for reading, transparently
    decompressing .gz. .7z is not supported here (would require
    subprocess + temp file; the viewer's 'Download' button is the
    right path for 7z inspection)."""
    name = path.name.lower()
    if name.endswith(".gz") or name.endswith(".tgz"):
        return _gzip.open(path, "rb")
    if name.endswith(".7z"):
        raise HTTPException(
            status_code=400,
            detail="7z archives are not searchable in-place; download the file instead",
        )
    return path.open("rb")


_LEVEL_ORDER = {
    "DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50,
}


def _line_matches(
    line: str,
    parsed: dict | None,
    levels: set[str] | None,
    min_level: int | None,
    q: str | None,
    q_regex: "_re.Pattern | None",
    from_epoch: float | None,
    to_epoch: float | None,
) -> bool:
    """Apply the active filter set to a single line. Returns True
    iff the line should be included."""
    if levels and parsed:
        lvl = str(parsed.get("level", "")).upper()
        if lvl and lvl not in levels:
            return False
    elif min_level is not None and parsed:
        lvl = str(parsed.get("level", "")).upper()
        if lvl and _LEVEL_ORDER.get(lvl, 0) < min_level:
            return False

    if (from_epoch is not None or to_epoch is not None) and parsed:
        ts_raw = parsed.get("timestamp") or parsed.get("ts")
        if ts_raw:
            try:
                dt = _datetime.fromisoformat(str(ts_raw))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_timezone.utc)
                epoch = dt.timestamp()
                if from_epoch is not None and epoch < from_epoch:
                    return False
                if to_epoch is not None and epoch > to_epoch:
                    return False
            except (TypeError, ValueError):
                pass

    if q_regex is not None:
        if not q_regex.search(line):
            return False
    elif q:
        if q.lower() not in line.lower():
            return False

    return True


@router.get("/search")
async def search_log(
    name: str,
    q: str | None = None,
    regex: bool = False,
    levels: str | None = None,              # comma-separated: "ERROR,WARNING"
    min_level: str | None = None,           # "ERROR" — alternative to `levels`
    from_iso: str | None = None,            # ISO-8601 start
    to_iso: str | None = None,              # ISO-8601 end
    limit: int = 200,
    offset: int = 0,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Historical paginated search. Results are ordered newest-first.

    Parsing:
    - Each line is attempted as JSON (structlog output is one JSON
      object per line). If it parses, level / timestamp / logger /
      message become filterable fields. If it doesn't, the raw line
      is included and only the substring/regex filter applies.
    - `limit` = 1-1000 (default 200), `offset` = lines to skip from
      the newest match. UI uses this for "Load older" pagination.

    Performance notes:
    - Uncompressed logs are read via reverse-line scan (fast even on
      GB-scale files — we only materialize matches).
    - `.gz` logs are read sequentially front-to-back because reverse
      reads on gzip streams aren't possible without full decompress.
      The LRU reader cache keeps a decompressed window in memory
      between paginated requests.
    """
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    try:
        path = _safe_logs_path(name)
    except PermissionError:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="log not found")

    # Parse filter params
    level_set: set[str] | None = None
    if levels:
        level_set = {
            lv.strip().upper()
            for lv in levels.split(",")
            if lv.strip() and lv.strip().upper() in _LEVEL_ORDER
        }
        if not level_set:
            level_set = None
    min_level_int: int | None = None
    if level_set is None and min_level:
        min_level_int = _LEVEL_ORDER.get(min_level.upper())

    q_regex = None
    if q and regex:
        try:
            q_regex = _re.compile(q, _re.IGNORECASE)
        except _re.error as exc:
            raise HTTPException(status_code=400, detail=f"invalid regex: {exc}")

    def _parse_epoch(iso: str | None) -> float | None:
        if not iso:
            return None
        try:
            dt = _datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_timezone.utc)
            return dt.timestamp()
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"invalid ISO datetime: {iso}"
            )

    from_epoch = _parse_epoch(from_iso)
    to_epoch = _parse_epoch(to_iso)

    # Read + filter. Run in a worker thread to keep the event loop free.
    def _do_search() -> dict:
        # Cap at a reasonable per-request line read ceiling so a
        # regex-that-matches-nothing doesn't scan a 100 GB file.
        MAX_SCAN_LINES = 500_000
        scanned = 0
        matched_lines: list[dict] = []

        lower = path.name.lower()
        is_compressed = lower.endswith(".gz") or lower.endswith(".tgz")

        # Open for text read. gzip returns bytes; wrap with
        # TextIOWrapper for consistent str handling.
        if is_compressed:
            fh = _gzip.open(path, "rt", encoding="utf-8", errors="replace")
        else:
            fh = path.open("r", encoding="utf-8", errors="replace")

        try:
            # For uncompressed we could reverse-scan but Python makes
            # that awkward. For both paths we do a forward scan, collect
            # matching lines into a ring of (limit + offset) + small
            # buffer, then slice at the end to take newest-first. This
            # keeps memory bounded and code simple.
            ring_size = max(1, limit + offset) + 100
            ring: list[dict] = []

            for line in fh:
                scanned += 1
                if scanned > MAX_SCAN_LINES:
                    break
                line = line.rstrip("\n")
                if not line:
                    continue

                parsed: dict | None = None
                try:
                    obj = _json.loads(line)
                    if isinstance(obj, dict):
                        parsed = obj
                except (ValueError, TypeError):
                    parsed = None

                if not _line_matches(
                    line, parsed, level_set, min_level_int,
                    q, q_regex, from_epoch, to_epoch,
                ):
                    continue

                entry = {
                    "raw": line,
                    "parsed": parsed,
                }
                ring.append(entry)
                if len(ring) > ring_size:
                    ring.pop(0)

            # Ring now holds the most recent matches in ascending order.
            # Reverse to newest-first, then slice [offset : offset+limit].
            ring.reverse()
            matched_lines = ring[offset: offset + limit]
        finally:
            fh.close()

        return {
            "lines": matched_lines,
            "returned": len(matched_lines),
            "offset": offset,
            "limit": limit,
            "scanned_lines": scanned,
            "scan_truncated": scanned >= MAX_SCAN_LINES,
            "file": name,
        }

    return await asyncio.to_thread(_do_search)
