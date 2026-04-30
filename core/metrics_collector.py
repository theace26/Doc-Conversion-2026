"""
Resource metrics collector — system metrics, disk snapshots, activity events.

Scheduled by APScheduler:
  - collect_metrics()        — every 30s, lightweight psutil snapshot
  - collect_disk_snapshot()  — every 6h, directory walks (expensive)
  - purge_old_metrics()      — daily at 03:00, delete rows older than 90 days
"""

import json
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone

import psutil
import aiosqlite
import structlog

from core.database import DB_PATH

log = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


@asynccontextmanager
async def _db():
    """Metrics-local DB connection with busy_timeout for concurrent access."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA busy_timeout=10000")
        yield conn


_process: psutil.Process | None = None


def _get_process() -> psutil.Process:
    global _process
    if _process is None:
        _process = psutil.Process(os.getpid())
    return _process


def _human_bytes(n: int | float) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


# ── System metrics collection ────────────────────────────────────────────────


def _collect_system_snapshot() -> dict:
    """Collect a point-in-time system metrics snapshot. Runs in thread."""
    proc = _get_process()
    with proc.oneshot():
        cpu_proc = proc.cpu_percent(interval=None)
        mem_info = proc.memory_info()
        try:
            io_counters = proc.io_counters()
            io_read = io_counters.read_bytes
            io_write = io_counters.write_bytes
        except (psutil.AccessDenied, AttributeError):
            io_read = None
            io_write = None
        threads = proc.num_threads()

    cpu_system = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True) or 1
    mem_sys = psutil.virtual_memory()

    return {
        "cpu_percent_total": cpu_proc,
        "cpu_percent_system": cpu_system,
        "cpu_count": cpu_count,
        "mem_rss_bytes": mem_info.rss,
        "mem_rss_percent": round(mem_info.rss / mem_sys.total * 100, 2) if mem_sys.total else 0,
        "mem_system_total_bytes": mem_sys.total,
        "mem_system_used_percent": mem_sys.percent,
        "io_read_bytes": io_read,
        "io_write_bytes": io_write,
        "thread_count": threads,
    }


async def _get_active_task_counts() -> dict:
    """Count currently active tasks from the running app."""
    active_bulk = 0
    active_scan = 0
    active_conv = 0

    try:
        from core.bulk_worker import get_all_jobs
        jobs = get_all_jobs()
        active_bulk = sum(1 for j in jobs.values() if j.status in ("running", "paused", "scanning"))
    except Exception:
        pass

    try:
        from core.lifecycle_scanner import get_scan_state
        scan_state = get_scan_state()
        active_scan = 1 if scan_state.get("running", False) else 0
    except Exception:
        pass

    try:
        from core.converter import _progress_queues
        active_conv = len(_progress_queues)
    except Exception:
        pass

    return {
        "active_bulk_jobs": active_bulk,
        "active_lifecycle_scan": active_scan,
        "active_conversions": active_conv,
    }


async def _insert_system_metrics(snapshot: dict) -> None:
    """Insert a system metrics row. Retries on 'database is locked'."""
    for attempt in range(_MAX_RETRIES):
        try:
            async with _db() as conn:
                await conn.execute(
                    """INSERT INTO system_metrics
                       (cpu_percent_total, cpu_percent_system, cpu_count,
                        mem_rss_bytes, mem_rss_percent, mem_system_total_bytes, mem_system_used_percent,
                        io_read_bytes, io_write_bytes, thread_count,
                        active_bulk_jobs, active_lifecycle_scan, active_conversions)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snapshot["cpu_percent_total"],
                        snapshot["cpu_percent_system"],
                        snapshot["cpu_count"],
                        snapshot["mem_rss_bytes"],
                        snapshot["mem_rss_percent"],
                        snapshot["mem_system_total_bytes"],
                        snapshot["mem_system_used_percent"],
                        snapshot["io_read_bytes"],
                        snapshot["io_write_bytes"],
                        snapshot["thread_count"],
                        snapshot["active_bulk_jobs"],
                        snapshot["active_lifecycle_scan"],
                        snapshot["active_conversions"],
                    ),
                )
                await conn.commit()
            return
        except Exception as e:
            if "database is locked" in str(e) and attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            raise


async def collect_metrics() -> None:
    """Called by APScheduler every 120 seconds."""
    try:
        await asyncio.wait_for(_do_collect_metrics(), timeout=30.0)
    except asyncio.TimeoutError:
        log.warning("metrics_collection_timeout", msg="Metrics collection timed out after 30s")
    except Exception:
        log.warning("metrics_collection_failed", exc_info=True)


async def _do_collect_metrics() -> None:
    """Inner metrics collection — separated for timeout wrapping."""
    snapshot = await asyncio.to_thread(_collect_system_snapshot)
    tasks = await _get_active_task_counts()
    snapshot.update(tasks)
    await _insert_system_metrics(snapshot)


# ── Disk metrics collection ──────────────────────────────────────────────────


def _walk_dir(path: Path, exclude_parts: set[str] | None = None) -> tuple[int, int]:
    """Walk directory tree, return (total_bytes, file_count). Runs in a thread."""
    total = 0
    count = 0
    if not path.exists() or not path.is_dir():
        return 0, 0
    try:
        for f in path.rglob("*"):
            if not f.is_file():
                continue
            if exclude_parts and exclude_parts & set(f.parts):
                continue
            try:
                total += f.stat().st_size
                count += 1
            except OSError:
                continue
    except OSError:
        pass
    return total, count


def _stat_file(path: Path) -> int:
    """Stat a single file, return bytes or 0."""
    try:
        if path.exists() and path.is_file():
            return path.stat().st_size
    except OSError:
        pass
    return 0


def _collect_disk_snapshot_impl() -> dict:
    """Walk MarkFlow directories and measure sizes. Runs in thread."""
    # v0.34.2 BUG-010: was reading BULK_OUTPUT_PATH and OUTPUT_DIR env
    # vars directly, so every 6h disk snapshot persisted byte counts
    # for the wrong directory whenever Storage Manager's configured
    # output diverged from the env defaults. The metrics time-series
    # was silently drifting; resolve through the canonical resolver
    # so reconfigurations take effect on the very next snapshot.
    from core.storage_paths import get_output_root
    output_repo = get_output_root()
    trash_path = output_repo / ".trash"

    # Trash (separate from output-repo to avoid double-counting)
    trash_bytes, trash_files = _walk_dir(trash_path)

    # Output repo excluding .trash
    repo_bytes, repo_files = _walk_dir(output_repo, exclude_parts={".trash"})

    # Conversion output (same root post-v0.34.1; see api/routes/admin.py
    # comment — kept as a separate row for operator clarity).
    conv_output = get_output_root()
    conv_bytes, conv_files = _walk_dir(conv_output)

    # Database (db + wal + shm)
    db_path = Path(os.environ.get("DB_PATH", "/app/data/markflow.db"))
    db_bytes = _stat_file(db_path)
    db_bytes += _stat_file(db_path.parent / (db_path.name + "-wal"))
    db_bytes += _stat_file(db_path.parent / (db_path.name + "-shm"))

    # Logs
    logs_dir = Path(os.environ.get("LOGS_DIR", "logs"))
    logs_bytes, _ = _walk_dir(logs_dir)

    # Meilisearch data
    meili_path = Path(os.environ.get("MEILI_DATA_PATH", "/meili_data"))
    meili_bytes, _ = _walk_dir(meili_path)

    # v0.34.6 BUG-013: do NOT add conv_bytes here. Post-v0.34.1 the
    # resolver returns one configured root for both bulk and single-file
    # conversion, so conv_output == output_repo. conv_bytes is therefore
    # equal to repo_bytes + trash_bytes already (it walks the same root
    # without the .trash exclusion). The pre-fix formula double-counted
    # the entire output share whenever the conv walk succeeded, which is
    # what made the Resources page disk card balloon to ~2× actual usage.
    # The conv_bytes column is still persisted for operator-clarity in
    # the admin breakdown UI (different workflow label) but must not
    # contribute to the total.
    total_bytes = repo_bytes + trash_bytes + db_bytes + logs_bytes + meili_bytes

    # Volume info
    vol_total = vol_used = vol_free = 0
    vol_pct = 0.0
    try:
        usage = psutil.disk_usage(str(output_repo) if output_repo.exists() else "/")
        vol_total = usage.total
        vol_used = usage.used
        vol_free = usage.free
        vol_pct = usage.percent
    except OSError:
        pass

    return {
        "output_repo_bytes": repo_bytes,
        "output_repo_files": repo_files,
        "trash_bytes": trash_bytes,
        "trash_files": trash_files,
        "conversion_output_bytes": conv_bytes,
        "conversion_output_files": conv_files,
        "database_bytes": db_bytes,
        "logs_bytes": logs_bytes,
        "meilisearch_bytes": meili_bytes,
        "total_bytes": total_bytes,
        "volume_total_bytes": vol_total,
        "volume_used_bytes": vol_used,
        "volume_free_bytes": vol_free,
        "volume_used_percent": vol_pct,
    }


async def _insert_disk_metrics(disk: dict) -> None:
    """Insert a disk metrics row."""
    async with _db() as conn:
        await conn.execute(
            """INSERT INTO disk_metrics
               (output_repo_bytes, output_repo_files, trash_bytes, trash_files,
                conversion_output_bytes, conversion_output_files, database_bytes,
                logs_bytes, meilisearch_bytes, total_bytes,
                volume_total_bytes, volume_used_bytes, volume_free_bytes, volume_used_percent)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                disk["output_repo_bytes"],
                disk["output_repo_files"],
                disk["trash_bytes"],
                disk["trash_files"],
                disk["conversion_output_bytes"],
                disk["conversion_output_files"],
                disk["database_bytes"],
                disk["logs_bytes"],
                disk["meilisearch_bytes"],
                disk["total_bytes"],
                disk["volume_total_bytes"],
                disk["volume_used_bytes"],
                disk["volume_free_bytes"],
                disk["volume_used_percent"],
            ),
        )
        await conn.commit()


async def collect_disk_snapshot() -> None:
    """Called by APScheduler every 6 hours."""
    try:
        disk = await asyncio.to_thread(_collect_disk_snapshot_impl)
        await _insert_disk_metrics(disk)
        log.info("disk_snapshot_collected", total_bytes=disk["total_bytes"])
    except Exception:
        log.warning("disk_metrics_collection_failed", exc_info=True)


# ── Purge old metrics ────────────────────────────────────────────────────────


async def purge_old_metrics() -> None:
    """Called by APScheduler daily. Delete metrics older than 90 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        async with _db() as conn:
            await conn.execute("DELETE FROM system_metrics WHERE timestamp < ?", (cutoff,))
            await conn.execute("DELETE FROM disk_metrics WHERE timestamp < ?", (cutoff,))
            await conn.execute("DELETE FROM activity_events WHERE timestamp < ?", (cutoff,))
            await conn.commit()
        log.info("metrics_purged", cutoff=cutoff)
    except Exception:
        log.warning("metrics_purge_failed", exc_info=True)

    # Also purge auto-conversion metrics
    try:
        from core.auto_metrics_aggregator import purge_old_auto_metrics
        await purge_old_auto_metrics()
    except Exception:
        log.warning("auto_metrics_purge_failed", exc_info=True)


# ── Activity event recording ─────────────────────────────────────────────────


async def record_activity_event(
    event_type: str,
    description: str,
    metadata: dict | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Record a notable activity event. Fire-and-forget — never raises."""
    try:
        async with _db() as conn:
            await conn.execute(
                """INSERT INTO activity_events
                   (event_type, description, metadata, duration_seconds)
                   VALUES (?, ?, ?, ?)""",
                (
                    event_type,
                    description,
                    json.dumps(metadata) if metadata else None,
                    duration_seconds,
                ),
            )
            await conn.commit()
    except Exception:
        log.warning("activity_event_failed", event_type=event_type, exc_info=True)


# ── Query helpers (used by API endpoints) ────────────────────────────────────


def _range_to_cutoff(range_str: str) -> str:
    """Convert a range string like '24h' to an ISO timestamp cutoff."""
    mapping = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    delta = mapping.get(range_str, timedelta(hours=24))
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _auto_resolution(range_str: str) -> str:
    """Pick a default resolution for a given time range."""
    mapping = {
        "1h": "raw",
        "6h": "1m",
        "24h": "5m",
        "7d": "15m",
        "30d": "1h",
        "90d": "6h",
    }
    return mapping.get(range_str, "5m")


def _resolution_strftime(resolution: str) -> str | None:
    """Return strftime bucket expression for the given resolution, or None for raw."""
    if resolution == "raw":
        return None
    mapping = {
        "1m": "%Y-%m-%dT%H:%M:00Z",
        "5m": None,  # handled specially
        "15m": None,  # handled specially
        "1h": "%Y-%m-%dT%H:00:00Z",
        "6h": None,  # handled specially
    }
    return mapping.get(resolution)


def _bucket_expression(resolution: str) -> str:
    """Return SQL expression for bucketing timestamps by resolution."""
    if resolution == "raw":
        return "timestamp"
    if resolution == "1m":
        return "strftime('%Y-%m-%dT%H:%M:00Z', timestamp)"
    if resolution == "5m":
        return "strftime('%Y-%m-%dT%H:', timestamp) || printf('%02d', (CAST(strftime('%M', timestamp) AS INTEGER) / 5) * 5) || ':00Z'"
    if resolution == "15m":
        return "strftime('%Y-%m-%dT%H:', timestamp) || printf('%02d', (CAST(strftime('%M', timestamp) AS INTEGER) / 15) * 15) || ':00Z'"
    if resolution == "1h":
        return "strftime('%Y-%m-%dT%H:00:00Z', timestamp)"
    if resolution == "6h":
        return "strftime('%Y-%m-%dT', timestamp) || printf('%02d', (CAST(strftime('%H', timestamp) AS INTEGER) / 6) * 6) || ':00:00Z'"
    return "timestamp"


async def query_system_metrics(range_str: str = "24h", resolution: str | None = None) -> list[dict]:
    """Query system_metrics with optional downsampling."""
    if resolution is None:
        resolution = _auto_resolution(range_str)
    cutoff = _range_to_cutoff(range_str)

    if resolution == "raw":
        sql = """
            SELECT timestamp, cpu_percent_total, cpu_percent_system, cpu_count,
                   mem_rss_bytes, mem_rss_percent, mem_system_total_bytes, mem_system_used_percent,
                   io_read_bytes, io_write_bytes, thread_count,
                   active_bulk_jobs, active_lifecycle_scan, active_conversions
            FROM system_metrics
            WHERE timestamp >= ?
            ORDER BY timestamp
        """
        async with _db() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(sql, (cutoff,)) as cur:
                rows = await cur.fetchall()
            return [dict(r) for r in rows]

    bucket = _bucket_expression(resolution)
    sql = f"""
        SELECT
            {bucket} AS timestamp,
            AVG(cpu_percent_total) AS cpu_percent_total,
            MAX(cpu_percent_total) AS cpu_peak,
            AVG(cpu_percent_system) AS cpu_percent_system,
            AVG(mem_rss_bytes) AS mem_rss_bytes,
            MAX(mem_rss_bytes) AS mem_rss_peak,
            AVG(mem_rss_percent) AS mem_rss_percent,
            AVG(mem_system_used_percent) AS mem_system_used_percent,
            MAX(io_read_bytes) AS io_read_bytes,
            MAX(io_write_bytes) AS io_write_bytes,
            MAX(thread_count) AS thread_count,
            MAX(active_bulk_jobs) AS active_bulk_jobs,
            MAX(active_lifecycle_scan) AS active_lifecycle_scan,
            MAX(active_conversions) AS active_conversions
        FROM system_metrics
        WHERE timestamp >= ?
        GROUP BY {bucket}
        ORDER BY {bucket}
    """
    async with _db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, (cutoff,)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def query_disk_metrics(range_str: str = "30d") -> list[dict]:
    """Query disk_metrics within range."""
    cutoff = _range_to_cutoff(range_str)
    async with _db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM disk_metrics WHERE timestamp >= ? ORDER BY timestamp",
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def query_activity_events(
    range_str: str = "7d",
    event_types: list[str] | None = None,
    limit: int = 100,
) -> tuple[list[dict], int]:
    """Query activity events with optional type filter. Returns (events, total)."""
    cutoff = _range_to_cutoff(range_str)
    limit = min(limit, 500)

    where = "WHERE timestamp >= ?"
    params: list = [cutoff]

    if event_types:
        placeholders = ",".join("?" for _ in event_types)
        where += f" AND event_type IN ({placeholders})"
        params.extend(event_types)

    # Count total
    async with _db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            f"SELECT COUNT(*) as c FROM activity_events {where}", tuple(params)
        ) as cur:
            row = await cur.fetchone()
            total = row["c"] if row else 0

        # Fetch page
        async with conn.execute(
            f"SELECT * FROM activity_events {where} ORDER BY timestamp DESC LIMIT ?",
            tuple(params + [limit]),
        ) as cur:
            rows = await cur.fetchall()

    events = []
    for r in rows:
        d = dict(r)
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        events.append(d)

    return events, total


async def compute_summary(period_days: int = 30) -> dict:
    """Compute the executive resource summary for the IT admin pitch card."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=period_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result: dict = {
        "period_days": period_days,
        "period_start": cutoff,
        "period_end": now,
    }

    async with _db() as conn:
        conn.row_factory = aiosqlite.Row

        # ── Uptime (count samples * 30s / 3600) ────────────────
        async with conn.execute(
            "SELECT COUNT(*) as c FROM system_metrics WHERE timestamp >= ?", (cutoff,)
        ) as cur:
            row = await cur.fetchone()
            sample_count = row["c"] if row else 0
        result["uptime_hours"] = round(sample_count * 30 / 3600, 1)

        # ── CPU stats ──────────────────────────────────────────
        async with conn.execute(
            """SELECT AVG(cpu_percent_total) as avg_cpu,
                      MAX(cpu_percent_total) as peak_cpu,
                      AVG(cpu_percent_system) as avg_sys,
                      MAX(cpu_count) as cpu_count
               FROM system_metrics WHERE timestamp >= ?""",
            (cutoff,),
        ) as cur:
            cpu_row = await cur.fetchone()

        # P95 CPU
        async with conn.execute(
            "SELECT cpu_percent_total FROM system_metrics WHERE timestamp >= ? ORDER BY cpu_percent_total",
            (cutoff,),
        ) as cur:
            cpu_vals = [r["cpu_percent_total"] for r in await cur.fetchall()]

        # Idle baseline (when no tasks active)
        async with conn.execute(
            """SELECT AVG(cpu_percent_total) as idle
               FROM system_metrics
               WHERE timestamp >= ?
                 AND active_bulk_jobs = 0
                 AND active_conversions = 0
                 AND active_lifecycle_scan = 0""",
            (cutoff,),
        ) as cur:
            idle_row = await cur.fetchone()

        cpu_avg = round(cpu_row["avg_cpu"], 1) if cpu_row and cpu_row["avg_cpu"] is not None else 0
        cpu_peak = round(cpu_row["peak_cpu"], 1) if cpu_row and cpu_row["peak_cpu"] is not None else 0
        cpu_sys_avg = round(cpu_row["avg_sys"], 1) if cpu_row and cpu_row["avg_sys"] is not None else 0
        cpu_count = cpu_row["cpu_count"] if cpu_row and cpu_row["cpu_count"] else 1
        cpu_p95 = round(cpu_vals[int(len(cpu_vals) * 0.95)] if cpu_vals else 0, 1)
        idle_baseline = round(idle_row["idle"], 1) if idle_row and idle_row["idle"] is not None else (
            round(cpu_vals[int(len(cpu_vals) * 0.05)], 1) if cpu_vals else 0
        )

        result["cpu"] = {
            "process_avg_percent": cpu_avg,
            "process_peak_percent": cpu_peak,
            "process_p95_percent": cpu_p95,
            "system_avg_percent": cpu_sys_avg,
            "idle_baseline_percent": idle_baseline,
            "core_count": cpu_count,
            "description": f"MarkFlow averaged {cpu_avg}% CPU ({idle_baseline}% idle, {cpu_peak}% peak during bulk conversion)",
        }

        # ── Memory stats ───────────────────────────────────────
        async with conn.execute(
            """SELECT AVG(mem_rss_bytes) as avg_rss, MAX(mem_rss_bytes) as peak_rss,
                      AVG(mem_rss_percent) as avg_pct,
                      MAX(mem_system_total_bytes) as sys_total
               FROM system_metrics WHERE timestamp >= ?""",
            (cutoff,),
        ) as cur:
            mem_row = await cur.fetchone()

        async with conn.execute(
            "SELECT mem_rss_bytes FROM system_metrics WHERE timestamp >= ? ORDER BY mem_rss_bytes",
            (cutoff,),
        ) as cur:
            mem_vals = [r["mem_rss_bytes"] for r in await cur.fetchall()]

        rss_avg = int(mem_row["avg_rss"]) if mem_row and mem_row["avg_rss"] else 0
        rss_peak = int(mem_row["peak_rss"]) if mem_row and mem_row["peak_rss"] else 0
        rss_p95 = mem_vals[int(len(mem_vals) * 0.95)] if mem_vals else 0
        sys_total = int(mem_row["sys_total"]) if mem_row and mem_row["sys_total"] else 0
        pct_avg = round(mem_row["avg_pct"], 1) if mem_row and mem_row["avg_pct"] is not None else 0

        # Stability check: compare first 10% avg to last 10%
        stable = True
        if len(mem_vals) >= 10:
            n10 = max(1, len(mem_vals) // 10)
            first_avg = sum(mem_vals[:n10]) / n10
            last_avg = sum(mem_vals[-n10:]) / n10
            if first_avg > 0:
                stable = abs(last_avg - first_avg) / first_avg < 0.10

        stability_text = "No memory growth detected." if stable else "Memory growth detected over period."
        result["memory"] = {
            "rss_avg_bytes": rss_avg,
            "rss_avg_human": _human_bytes(rss_avg),
            "rss_peak_bytes": rss_peak,
            "rss_peak_human": _human_bytes(rss_peak),
            "rss_p95_bytes": rss_p95,
            "rss_p95_human": _human_bytes(rss_p95),
            "system_total_bytes": sys_total,
            "system_total_human": _human_bytes(sys_total),
            "percent_of_system_avg": pct_avg,
            "stable": stable,
            "description": f"Stable at ~{_human_bytes(rss_avg)} ({pct_avg}% of {_human_bytes(sys_total)}). {stability_text}",
        }

        # ── Disk stats ─────────────────────────────────────────
        async with conn.execute(
            "SELECT * FROM disk_metrics WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
            (cutoff,),
        ) as cur:
            latest_disk = await cur.fetchone()
            latest_disk = dict(latest_disk) if latest_disk else {}

        async with conn.execute(
            "SELECT * FROM disk_metrics WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
            (cutoff,),
        ) as cur:
            earliest_disk = await cur.fetchone()
            earliest_disk = dict(earliest_disk) if earliest_disk else {}

        current_total = latest_disk.get("total_bytes", 0)
        vol_free = latest_disk.get("volume_free_bytes", 0)
        growth_per_day = 0
        if earliest_disk and latest_disk:
            earliest_ts = earliest_disk.get("timestamp", "")
            latest_ts = latest_disk.get("timestamp", "")
            if earliest_ts and latest_ts and earliest_ts != latest_ts:
                try:
                    t0 = datetime.fromisoformat(earliest_ts.replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
                    days = max((t1 - t0).total_seconds() / 86400, 1)
                    growth_per_day = int((latest_disk.get("total_bytes", 0) - earliest_disk.get("total_bytes", 0)) / days)
                except Exception:
                    pass

        projected = current_total + (growth_per_day * 30) if growth_per_day > 0 else current_total
        result["disk"] = {
            "current_total_bytes": current_total,
            "current_total_human": _human_bytes(current_total),
            "growth_bytes_per_day": max(growth_per_day, 0),
            "growth_human_per_day": _human_bytes(max(growth_per_day, 0)),
            "projected_30d_bytes": projected,
            "projected_30d_human": _human_bytes(projected),
            "volume_free_bytes": vol_free,
            "volume_free_human": _human_bytes(vol_free),
            "description": f"{_human_bytes(current_total)} total, growing ~{_human_bytes(max(growth_per_day, 0))}/day. {_human_bytes(vol_free)} free on volume.",
        }

        # ── I/O stats ──────────────────────────────────────────
        async with conn.execute(
            "SELECT io_read_bytes, io_write_bytes, timestamp FROM system_metrics "
            "WHERE timestamp >= ? AND io_read_bytes IS NOT NULL ORDER BY timestamp ASC LIMIT 1",
            (cutoff,),
        ) as cur:
            first_io = await cur.fetchone()
            first_io = dict(first_io) if first_io else {}

        async with conn.execute(
            "SELECT io_read_bytes, io_write_bytes, timestamp FROM system_metrics "
            "WHERE timestamp >= ? AND io_read_bytes IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
            (cutoff,),
        ) as cur:
            last_io = await cur.fetchone()
            last_io = dict(last_io) if last_io else {}

        read_avg = 0
        write_avg = 0
        if first_io and last_io and first_io.get("timestamp") != last_io.get("timestamp"):
            try:
                t0 = datetime.fromisoformat(first_io["timestamp"].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(last_io["timestamp"].replace("Z", "+00:00"))
                secs = max((t1 - t0).total_seconds(), 1)
                read_avg = int((last_io.get("io_read_bytes", 0) - first_io.get("io_read_bytes", 0)) / secs)
                write_avg = int((last_io.get("io_write_bytes", 0) - first_io.get("io_write_bytes", 0)) / secs)
            except Exception:
                pass

        result["io"] = {
            "read_avg_bytes_per_sec": max(read_avg, 0),
            "read_avg_human": _human_bytes(max(read_avg, 0)) + "/s",
            "write_avg_bytes_per_sec": max(write_avg, 0),
            "write_avg_human": _human_bytes(max(write_avg, 0)) + "/s",
            "description": f"Average disk I/O: {_human_bytes(max(read_avg, 0))}/s read, {_human_bytes(max(write_avg, 0))}/s write",
        }

        # ── Activity stats ─────────────────────────────────────
        async with conn.execute(
            "SELECT COUNT(*) as c FROM activity_events WHERE timestamp >= ?", (cutoff,)
        ) as cur:
            total_events = (await cur.fetchone())["c"]

        async with conn.execute(
            "SELECT COUNT(*) as c FROM activity_events WHERE timestamp >= ? AND event_type='bulk_end'",
            (cutoff,),
        ) as cur:
            bulk_completed = (await cur.fetchone())["c"]

        async with conn.execute(
            "SELECT COUNT(*) as c FROM activity_events WHERE timestamp >= ? AND event_type='lifecycle_scan_end'",
            (cutoff,),
        ) as cur:
            scan_count = (await cur.fetchone())["c"]

        async with conn.execute(
            "SELECT COUNT(*) as c FROM activity_events WHERE timestamp >= ? AND event_type='error'",
            (cutoff,),
        ) as cur:
            error_count = (await cur.fetchone())["c"]

        # Total files converted from bulk_end metadata
        async with conn.execute(
            "SELECT metadata FROM activity_events WHERE timestamp >= ? AND event_type='bulk_end'",
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
        total_files = 0
        total_duration = 0
        for r in rows:
            try:
                m = json.loads(r["metadata"]) if r["metadata"] else {}
                total_files += m.get("converted", 0)
                total_duration += m.get("duration", 0)
            except Exception:
                pass

        avg_bulk_dur = round(total_duration / bulk_completed, 1) if bulk_completed else 0
        result["activity"] = {
            "total_events": total_events,
            "bulk_jobs_completed": bulk_completed,
            "total_files_converted": total_files,
            "lifecycle_scans": scan_count,
            "errors": error_count,
            "avg_bulk_duration_seconds": avg_bulk_dur,
            "description": f"{bulk_completed} bulk jobs ({total_files:,} files), {scan_count} lifecycle scans, {error_count} errors",
        }

    # ── Self governance (sync reads from prefs) ─────────────
    try:
        from core.database import get_all_preferences
        prefs = await get_all_preferences()
        worker_count = int(prefs.get("worker_count", "4"))
        priority = prefs.get("process_priority", "normal")
        affinity_raw = prefs.get("cpu_affinity_cores", "[]")
        try:
            affinity = json.loads(affinity_raw) if affinity_raw else []
        except Exception:
            affinity = []
        bh_start = prefs.get("scanner_business_hours_start", "06:00")
        bh_end = prefs.get("scanner_business_hours_end", "18:00")
        bh_enabled = prefs.get("scanner_enabled", "true") == "true"

        affinity_desc = f"pinned to cores {', '.join(str(c) for c in affinity)}" if affinity else "all cores"
        bh_desc = f"bulk runs during business hours ({bh_start}-{bh_end})" if bh_enabled else "no scheduling restrictions"
        result["self_governance"] = {
            "worker_count": worker_count,
            "process_priority": priority,
            "cpu_affinity": affinity,
            "business_hours_only": bh_enabled,
            "description": f"Configured: {worker_count} workers, {priority} priority, {affinity_desc}, {bh_desc}",
        }
    except Exception:
        result["self_governance"] = None

    return result
