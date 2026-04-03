"""
DB contention and query logging for diagnosing SQLite "database is locked" errors.

TEMPORARY — remove once lock contention is resolved.
See CLAUDE.md flag: "DB contention logging (v0.19.6.5)"

Three dedicated log files (all 1 GB cap, 3 sequential backups):
  - db-contention.log  — write acquire/release events with caller + hold duration
  - db-queries.log     — full SQL query log (statement, params, duration, caller)
  - db-active.log      — active-connection snapshots dumped on "database is locked"

Usage is automatic — instrumented in connection.py's get_db() and query helpers.
"""

import inspect
import logging
import logging.handlers
import os
import threading
import time
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────

_logs_dir = Path(os.getenv("LOGS_DIR", "logs"))
_MAX_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB
_BACKUP_COUNT = 3

# Master toggle — controlled by the db_contention_logging preference.
# Set via set_enabled() from the preferences API. Defaults to True so
# logging is active on startup before the DB preference is read.
_enabled = True


def set_enabled(enabled: bool):
    """Toggle contention logging on/off. Called when preference changes."""
    global _enabled
    _enabled = enabled


def is_enabled() -> bool:
    return _enabled

# ── Formatters ───────────────────────────────────────────────────────────────

_FMT = logging.Formatter(
    '%(asctime)s.%(msecs)03d | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)


def _make_handler(filename: str) -> logging.handlers.RotatingFileHandler:
    """Create a 1 GB rotating file handler."""
    _logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        _logs_dir / filename,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(_FMT)
    handler.setLevel(logging.DEBUG)
    return handler


def _make_logger(name: str, filename: str) -> logging.Logger:
    """Create a dedicated logger that writes only to its own file."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # don't leak into root/operational logs
    if not logger.handlers:
        logger.addHandler(_make_handler(filename))
    return logger


# ── Loggers ──────────────────────────────────────────────────────────────────

contention_log = _make_logger("db.contention", "db-contention.log")
query_log = _make_logger("db.queries", "db-queries.log")
active_log = _make_logger("db.active", "db-active.log")


# ── Caller identification ────────────────────────────────────────────────────

def _get_caller(skip_frames: int = 3) -> str:
    """Walk the stack to find the first frame outside core/db/.

    Returns 'module.function:line' for the caller that triggered the DB op.
    Falls back to the immediate caller if nothing outside core/db/ is found.
    """
    frame = inspect.currentframe()
    try:
        # Walk up the stack
        frames = inspect.getouterframes(frame)
        # Find the first frame NOT in core/db/ (skip our own frames)
        for i in range(skip_frames, len(frames)):
            f_info = frames[i]
            filename = f_info.filename
            # Skip frames inside core/db/ and Python internals
            if "/core/db/" in filename or "\\core\\db\\" in filename:
                continue
            if "/contextlib" in filename or "\\contextlib" in filename:
                continue
            if "/aiosqlite/" in filename or "\\aiosqlite\\" in filename:
                continue
            module = Path(filename).stem
            return f"{module}.{f_info.function}:{f_info.lineno}"
        # Fallback: immediate caller
        if len(frames) > skip_frames:
            f = frames[skip_frames]
            return f"{Path(f.filename).stem}.{f.function}:{f.lineno}"
        return "unknown"
    finally:
        del frame


# ── Active connection tracker (Option B) ─────────────────────────────────────

class ActiveConnectionTracker:
    """Thread-safe tracker of currently-held DB write connections.

    When a 'database is locked' error occurs, dump_active() logs every
    connection that's currently holding the DB, showing who is blocking.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active: dict[int, dict] = {}  # conn_id -> info
        self._counter = 0

    def register(self, caller: str, intent: str) -> int:
        """Register a new connection. Returns a unique conn_id."""
        with self._lock:
            self._counter += 1
            conn_id = self._counter
            self._active[conn_id] = {
                "caller": caller,
                "intent": intent,
                "acquired_at": time.time(),
                "thread": threading.current_thread().name,
            }
            return conn_id

    def release(self, conn_id: int):
        """Release a tracked connection."""
        with self._lock:
            self._active.pop(conn_id, None)

    def dump_active(self, error_caller: str) -> list[dict]:
        """Snapshot all active connections. Called on 'database is locked'."""
        now = time.time()
        with self._lock:
            snapshot = []
            for cid, info in self._active.items():
                held_ms = (now - info["acquired_at"]) * 1000
                snapshot.append({
                    "conn_id": cid,
                    "caller": info["caller"],
                    "intent": info["intent"],
                    "thread": info["thread"],
                    "held_ms": round(held_ms, 1),
                })
            return snapshot

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)


# Singleton tracker
tracker = ActiveConnectionTracker()


# ── Contention log helpers (Option A) ────────────────────────────────────────

def log_acquire(conn_id: int, caller: str, intent: str):
    """Log a DB connection being acquired."""
    if not _enabled:
        return
    active = tracker.active_count
    contention_log.info(
        "ACQUIRE  conn=%d | %s | intent=%s | active_connections=%d",
        conn_id, caller, intent, active,
    )


def log_release(conn_id: int, caller: str, intent: str, held_ms: float):
    """Log a DB connection being released."""
    if not _enabled:
        return
    contention_log.info(
        "RELEASE  conn=%d | %s | intent=%s | held_ms=%.1f",
        conn_id, caller, intent, held_ms,
    )


def log_lock_error(caller: str, error: str):
    """Log a 'database is locked' error with full active-connection dump."""
    snapshot = tracker.dump_active(caller)

    contention_log.error(
        "LOCKED   %s | error=%s | active_connections=%d",
        caller, error, len(snapshot),
    )
    for conn in snapshot:
        contention_log.error(
            "  HOLDING conn=%d | %s | intent=%s | thread=%s | held_ms=%.1f",
            conn["conn_id"], conn["caller"], conn["intent"],
            conn["thread"], conn["held_ms"],
        )

    # Also write to the dedicated active-connections log
    active_log.error(
        "LOCK_ERROR triggered by %s | error=%s", caller, error,
    )
    for conn in snapshot:
        active_log.error(
            "  ACTIVE  conn=%d | %s | intent=%s | thread=%s | held_ms=%.1f",
            conn["conn_id"], conn["caller"], conn["intent"],
            conn["thread"], conn["held_ms"],
        )
    if not snapshot:
        active_log.error("  (no tracked connections — lock holder may be external or already released)")


# ── Query log helper ─────────────────────────────────────────────────────────

def log_query(sql: str, params: tuple, caller: str, duration_ms: float,
              row_count: int | None = None, intent: str = "read"):
    """Log a full SQL query with params, timing, and caller."""
    if not _enabled:
        return
    # Truncate long SQL for readability (keep first 500 chars)
    sql_short = sql.strip().replace("\n", " ")
    if len(sql_short) > 500:
        sql_short = sql_short[:500] + "..."

    # Truncate params if very long
    params_str = str(params)
    if len(params_str) > 200:
        params_str = params_str[:200] + "..."

    rows_info = f" | rows={row_count}" if row_count is not None else ""
    query_log.info(
        "%s | %s | sql=%s | params=%s | dur_ms=%.1f%s",
        intent.upper(), caller, sql_short, params_str, duration_ms, rows_info,
    )
