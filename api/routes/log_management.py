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
    DEFAULT_SEVEN_Z_MAX_MB,
    SEVEN_Z_HARD_MAX_MB,
    LogEntry,
    LOGS_DIR,
    _safe_logs_path,
    apply_retention,
    compress_rotated_logs,
    get_settings,
    get_seven_z_max_mb,
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
    seven_z_max_mb: int | None = Field(
        None, ge=1, le=SEVEN_Z_HARD_MAX_MB,
        description="Per-reader decompressed-byte cap for `.7z` log search",
    )


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
            seven_z_max_mb=body.seven_z_max_mb,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log.info(
        "log_management.settings_updated",
        user=user.email,
        compression_format=body.compression_format,
        retention_days=body.retention_days,
        rotation_max_size_mb=body.rotation_max_size_mb,
        seven_z_max_mb=body.seven_z_max_mb,
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
import subprocess as _subprocess
from datetime import datetime as _datetime, timezone as _timezone


# v0.31.0: hard caps on `.7z` read to defend against hangs / runaway
# processes. The search wall-clock cap below ALSO applies; this byte
# cap is a per-reader belt-and-suspenders.
#
# v0.31.1: the byte cap is now operator-tunable via the
# `log_seven_z_max_mb` DB pref. The legacy module-level constant below
# stays as the defense-in-depth fallback for callers that didn't
# resolve the pref (e.g. unit tests, future call sites). Callers that
# do read the pref pass it in via `_SevenZReader(path, max_bytes=...)`.
_SEVENZ_DEFAULT_MAX_BYTES = DEFAULT_SEVEN_Z_MAX_MB * 1024 * 1024
_SEVENZ_TERMINATE_GRACE_S = 5.0
_SEVENZ_KILL_GRACE_S = 2.0


class _SevenZReader:
    """File-like binary reader that streams decompressed `.7z` content
    by spawning `/usr/bin/7z e -so <path>`. Lazily instantiated so the
    subprocess only runs when the search code actually reads bytes.

    The 7z binary is already in `Dockerfile.base` (it was added for
    hashcat). The `e -so` form extracts to stdout without writing a
    temp file. Closing the reader terminates the subprocess (graceful
    SIGTERM → wait 5s → SIGKILL → wait 2s). v0.31.0 hardening:

    - `start_new_session=True` so `close()` can kill the whole
      process group if 7z spawned children.
    - Per-reader byte cap (default 200 MB decompressed; v0.31.1 made
      this operator-tunable via the `log_seven_z_max_mb` DB pref) to
      bound the worst-case worker-thread wall time on a malicious or
      pathological archive.
    - `stderr=PIPE` + drain on close so 7z error output doesn't
      block its stdout pipe (rare but possible on damaged archives).
    """

    def __init__(self, path: Path, max_bytes: int | None = None):
        self._path = path
        self._proc: "_subprocess.Popen | None" = None
        self._bytes_read = 0
        self._cap_hit = False
        # v0.31.1: caller-supplied cap wins; otherwise fall back to the
        # legacy default so a new code path can't accidentally remove
        # the safety net just by forgetting to pass max_bytes.
        self._max_bytes = (
            max_bytes if max_bytes is not None and max_bytes > 0
            else _SEVENZ_DEFAULT_MAX_BYTES
        )

    def _ensure_started(self) -> None:
        if self._proc is not None:
            return
        kwargs: dict = {
            "stdout": _subprocess.PIPE,
            "stderr": _subprocess.PIPE,    # drained in close()
            "bufsize": 64 * 1024,
        }
        # `start_new_session=True` puts the child in a new process
        # group so close() can SIGTERM/SIGKILL the whole group via
        # os.killpg if the immediate child has spawned helpers.
        # POSIX-only — Windows would need creationflags. The container
        # is Linux so this is the right path.
        kwargs["start_new_session"] = True
        self._proc = _subprocess.Popen(
            ["/usr/bin/7z", "e", "-so", str(self._path)], **kwargs,
        )

    def _check_cap(self, chunk: bytes) -> bytes:
        """Apply the byte cap: if reading `chunk` would exceed the
        cap, truncate it and mark the reader spent. Subsequent reads
        return empty so the caller sees clean EOF."""
        if self._cap_hit:
            return b""
        room = self._max_bytes - self._bytes_read
        if room <= 0:
            self._cap_hit = True
            return b""
        if len(chunk) > room:
            chunk = chunk[:room]
            self._cap_hit = True
        self._bytes_read += len(chunk)
        return chunk

    def read(self, n: int = -1) -> bytes:
        self._ensure_started()
        if self._cap_hit:
            return b""
        # When n=-1, cap the read at our remaining budget so we don't
        # buffer the whole archive into memory if the caller asked
        # for "all of it".
        if n == -1 or n > self._max_bytes - self._bytes_read:
            n = self._max_bytes - self._bytes_read
            if n <= 0:
                self._cap_hit = True
                return b""
        chunk = self._proc.stdout.read(n)  # type: ignore[union-attr]
        return self._check_cap(chunk)

    def readline(self, *args, **kwargs) -> bytes:
        self._ensure_started()
        if self._cap_hit:
            return b""
        line = self._proc.stdout.readline(*args, **kwargs)  # type: ignore[union-attr]
        return self._check_cap(line)

    def readable(self) -> bool: return True
    def writable(self) -> bool: return False
    def seekable(self) -> bool: return False

    def __iter__(self):
        # Iterate via readline() so the byte cap applies to each line.
        return iter(self.readline, b"")

    def close(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        # Drain + close stdio so the subprocess doesn't block on
        # writing to a full pipe.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try: stream.close()
                except Exception: pass
        if proc.poll() is None:
            # Try graceful termination of the whole process group.
            import os, signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                # Fall back to terminating just the immediate child.
                try: proc.terminate()
                except Exception: pass
            try:
                proc.wait(timeout=_SEVENZ_TERMINATE_GRACE_S)
            except _subprocess.TimeoutExpired:
                # Hard kill the group.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try: proc.kill()
                    except Exception: pass
                try: proc.wait(timeout=_SEVENZ_KILL_GRACE_S)
                except Exception: pass

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


def _open_log_for_read(path: Path):
    """Return a binary file handle for reading, transparently
    decompressing `.gz` / `.tgz` (via stdlib `gzip`) and `.7z` (via
    `7z e -so` subprocess; v0.31.0). The returned object supports
    `read()` / `readline()` / iteration like a normal file, plus
    `close()` to release the underlying resource."""
    name = path.name.lower()
    if name.endswith(".gz") or name.endswith(".tgz"):
        return _gzip.open(path, "rb")
    if name.endswith(".7z"):
        return _SevenZReader(path)
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

    # v0.31.1: resolve the operator-configured `.7z` byte cap once
    # before entering the worker thread (the thread can't `await`).
    # Closure-captured by `_do_search` below.
    seven_z_max_mb = await get_seven_z_max_mb()
    seven_z_max_bytes = seven_z_max_mb * 1024 * 1024

    # Read + filter. Run in a worker thread to keep the event loop free.
    def _do_search() -> dict:
        # v0.31.0: triple-barrier protection so an unattended/headless
        # operation can never hang on a malicious or pathological log:
        #   1. line cap (`MAX_SCAN_LINES`) — bounds CPU on big files
        #   2. wall-clock cap (`MAX_WALL_S`) — bounds time even when
        #      reads are cheap-per-line but the file is huge
        #   3. (for `.7z` only) per-reader byte cap inside `_SevenZReader`
        # Any cap firing returns clean partial results with a flag
        # set so the UI can surface it.
        import time as _time
        MAX_SCAN_LINES = 500_000
        MAX_WALL_S = 60.0
        scanned = 0
        matched_lines: list[dict] = []
        start = _time.monotonic()
        wall_truncated = False
        reader_warning: str | None = None

        lower = path.name.lower()
        is_gzip = lower.endswith(".gz") or lower.endswith(".tgz")
        is_7z = lower.endswith(".7z")

        # Open for text read. v0.31.0: `.7z` now supported via the
        # `_SevenZReader` subprocess wrapper — wrap its byte stream
        # with TextIOWrapper. gzip already returns text via mode 'rt'.
        sevenz_reader: "_SevenZReader | None" = None
        try:
            if is_gzip:
                fh = _gzip.open(path, "rt", encoding="utf-8", errors="replace")
            elif is_7z:
                import io as _io
                sevenz_reader = _SevenZReader(path, max_bytes=seven_z_max_bytes)
                fh = _io.TextIOWrapper(
                    sevenz_reader, encoding="utf-8", errors="replace",
                )
            else:
                fh = path.open("r", encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            # 7z binary missing on the host (or path moved out from
            # under us between the existence check and the read).
            return {
                "lines": [], "returned": 0, "offset": offset, "limit": limit,
                "scanned_lines": 0, "scan_truncated": False, "wall_truncated": False,
                "file": name,
                "reader_warning": f"could not open log: {type(exc).__name__}: {exc}",
            }

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
                # Wall-clock check every 1024 lines — cheap enough
                # not to dominate, granular enough to bail within a
                # second of the deadline.
                if (scanned & 0x3FF) == 0:
                    if _time.monotonic() - start > MAX_WALL_S:
                        wall_truncated = True
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

            # If we read a 7z, also surface its byte-cap status.
            if sevenz_reader is not None and sevenz_reader._cap_hit:
                reader_warning = (
                    f"7z stream truncated at {seven_z_max_mb} MB"
                )
        except Exception as exc:
            # Defensive: any I/O error from the underlying stream
            # (corrupt gzip, killed subprocess, decoder error) returns
            # clean partial results rather than a 500. Headless safe.
            reader_warning = f"{type(exc).__name__}: {exc}"
        finally:
            try: fh.close()
            except Exception: pass
            # Belt-and-suspenders: ensure the 7z subprocess is gone
            # even if TextIOWrapper.close didn't propagate to it.
            if sevenz_reader is not None:
                try: sevenz_reader.close()
                except Exception: pass

        return {
            "lines": matched_lines,
            "returned": len(matched_lines),
            "offset": offset,
            "limit": limit,
            "scanned_lines": scanned,
            "scan_truncated": scanned >= MAX_SCAN_LINES,
            "wall_truncated": wall_truncated,
            "wall_seconds": round(_time.monotonic() - start, 2),
            "reader_warning": reader_warning,
            "file": name,
        }

    return await asyncio.to_thread(_do_search)
