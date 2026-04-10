"""
Single-writer connection pool with async write queue.

Provides 1 writer + N read-only connections, all pre-configured with
WAL mode, busy_timeout=30000, and foreign_keys=ON.  Writes are serialized
through an asyncio.Queue so only one write transaction is active at a time,
eliminating "database is locked" under concurrent load.

Usage::

    from core.db.pool import init_pool, shutdown_pool, get_pool

    # At app startup (after schema init):
    await init_pool(db_path)

    # At app shutdown:
    await shutdown_pool()

    # Anywhere in the app:
    pool = get_pool()
    rows = await pool.read("SELECT ...", ())
    row  = await pool.read_one("SELECT ... LIMIT 1", ())
    lid  = await pool.write("INSERT INTO ...", ())
    await pool.write_many([("INSERT ...", (v,)), ("UPDATE ...", (v2,))])
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal request types
# ---------------------------------------------------------------------------

@dataclass
class _WriteRequest:
    """A single SQL statement to execute on the writer connection."""
    sql: str
    params: tuple
    future: asyncio.Future


@dataclass
class _BatchWriteRequest:
    """Multiple SQL statements executed inside a single transaction."""
    statements: list[tuple[str, tuple]]
    future: asyncio.Future


# ---------------------------------------------------------------------------
# WriteQueue — serializes all writes through one connection
# ---------------------------------------------------------------------------

class WriteQueue:
    """Async queue that funnels every write through a single aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._queue: asyncio.Queue[_WriteRequest | _BatchWriteRequest | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._process_loop(), name="write-queue")

    async def stop(self) -> None:
        await self._queue.put(None)          # sentinel
        if self._task is not None:
            await self._task

    # -- public submit helpers ------------------------------------------------

    async def submit(self, sql: str, params: tuple = ()) -> int:
        """Submit a single write and wait for the result (lastrowid)."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int] = loop.create_future()
        await self._queue.put(_WriteRequest(sql=sql, params=params, future=fut))
        return await fut

    async def submit_batch(self, statements: list[tuple[str, tuple]]) -> None:
        """Submit multiple writes inside one transaction."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        await self._queue.put(_BatchWriteRequest(statements=statements, future=fut))
        return await fut

    # -- internal loop --------------------------------------------------------

    async def _process_loop(self) -> None:
        log.info("write_queue.started")
        while True:
            req = await self._queue.get()

            # Sentinel — shut down
            if req is None:
                log.info("write_queue.stopped")
                break

            if isinstance(req, _WriteRequest):
                await self._handle_single(req)
            elif isinstance(req, _BatchWriteRequest):
                await self._handle_batch(req)

    async def _handle_single(self, req: _WriteRequest) -> None:
        try:
            async with self._conn.execute(req.sql, req.params) as cursor:
                await self._conn.commit()
                req.future.set_result(cursor.lastrowid)
        except Exception as exc:
            try:
                await self._conn.rollback()
            except Exception:
                pass
            if not req.future.done():
                req.future.set_exception(exc)

    async def _handle_batch(self, req: _BatchWriteRequest) -> None:
        try:
            await self._conn.execute("BEGIN")
            for sql, params in req.statements:
                await self._conn.execute(sql, params)
            await self._conn.commit()
            req.future.set_result(None)
        except Exception as exc:
            try:
                await self._conn.rollback()
            except Exception:
                pass
            if not req.future.done():
                req.future.set_exception(exc)


# ---------------------------------------------------------------------------
# ConnectionPool — 1 writer + N readers
# ---------------------------------------------------------------------------

_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=30000",
    "PRAGMA foreign_keys=ON",
]


async def _open_connection(db_path: Path, *, read_only: bool = False) -> aiosqlite.Connection:
    """Open and configure a single aiosqlite connection."""
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    for pragma in _PRAGMAS:
        await conn.execute(pragma)
    if read_only:
        await conn.execute("PRAGMA query_only=ON")
    return conn


class ConnectionPool:
    """1 writer + *read_pool_size* read-only connections."""

    def __init__(self, db_path: Path, read_pool_size: int = 3) -> None:
        self._db_path = db_path
        self._read_pool_size = read_pool_size
        self._writer: aiosqlite.Connection | None = None
        self._write_queue: WriteQueue | None = None
        self._read_pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        self._all_readers: list[aiosqlite.Connection] = []

    async def open(self) -> None:
        """Open all connections and start the write queue."""
        self._writer = await _open_connection(self._db_path, read_only=False)
        self._write_queue = WriteQueue(self._writer)
        await self._write_queue.start()

        for _ in range(self._read_pool_size):
            reader = await _open_connection(self._db_path, read_only=True)
            self._all_readers.append(reader)
            await self._read_pool.put(reader)

        log.info("connection_pool.opened",
                 readers=self._read_pool_size, writer=1)

    async def close(self) -> None:
        """Drain the write queue, then close every connection."""
        if self._write_queue is not None:
            await self._write_queue.stop()

        for reader in self._all_readers:
            try:
                await reader.close()
            except Exception:
                pass
        self._all_readers.clear()

        if self._writer is not None:
            try:
                await self._writer.close()
            except Exception:
                pass
            self._writer = None

        log.info("connection_pool.closed")

    # -- read helpers ---------------------------------------------------------

    async def read(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a SELECT and return all rows as dicts."""
        conn = await self._read_pool.get()
        try:
            async with conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        finally:
            await self._read_pool.put(conn)

    async def read_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Execute a SELECT and return the first row as a dict (or None)."""
        conn = await self._read_pool.get()
        try:
            async with conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
        finally:
            await self._read_pool.put(conn)

    # -- write helpers --------------------------------------------------------

    async def write(self, sql: str, params: tuple = ()) -> int:
        """Execute a single INSERT/UPDATE/DELETE. Returns lastrowid."""
        assert self._write_queue is not None, "Pool not open"
        return await self._write_queue.submit(sql, params)

    async def write_many(self, statements: list[tuple[str, tuple]]) -> None:
        """Execute multiple writes in a single transaction."""
        assert self._write_queue is not None, "Pool not open"
        await self._write_queue.submit_batch(statements)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None


async def init_pool(db_path: str | Path, *, read_pool_size: int = 3) -> ConnectionPool:
    """Create and open the global connection pool.  Call once at startup."""
    global _pool
    if _pool is not None:
        log.warning("pool.already_initialized")
        return _pool
    _pool = ConnectionPool(Path(db_path), read_pool_size=read_pool_size)
    await _pool.open()
    return _pool


async def shutdown_pool() -> None:
    """Close the global pool.  Safe to call if pool was never initialized."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    """Return the global pool or raise RuntimeError if not yet initialized."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized — call init_pool() first")
    return _pool
