"""Hourly aggregator for auto-conversion historical metrics.

Reads raw system_metrics samples from the last hour, computes aggregates,
and inserts one row into auto_metrics. Also tracks conversion activity
and user request counts from activity_events.
"""

import structlog
from datetime import datetime, timedelta

from core.database import get_db, get_db_path, get_preference

log = structlog.get_logger(__name__)


async def aggregate_hourly_metrics():
    """Roll up the last hour of raw metrics into auto_metrics.

    Called by APScheduler every hour at :05 (5 minutes past to ensure
    the hour's last samples are in).
    """
    now = datetime.now()
    hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    hour_end = hour_start + timedelta(hours=1)
    bucket = hour_start.isoformat()
    dow = hour_start.weekday()

    try:
        async with get_db() as conn:
            # Idempotent — skip if already aggregated
            existing = await conn.execute_fetchall(
                "SELECT id FROM auto_metrics WHERE hour_bucket = ?",
                (bucket,),
            )
            if existing:
                return

            # Aggregate system_metrics for this hour
            rows = await conn.execute_fetchall(
                """
                SELECT
                    AVG(cpu_percent_total) as cpu_avg,
                    MAX(cpu_percent_total) as cpu_max,
                    AVG(mem_system_used_percent) as memory_avg,
                    MAX(mem_system_used_percent) as memory_peak,
                    COUNT(*) as sample_count
                FROM system_metrics
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )

            if not rows or rows[0]["sample_count"] == 0:
                log.debug(
                    "auto_metrics_no_samples",
                    hour_bucket=bucket,
                )
                return

            r = rows[0]

            # Compute p95 CPU in Python (SQLite lacks PERCENTILE_CONT)
            cpu_values = await conn.execute_fetchall(
                """
                SELECT cpu_percent_total FROM system_metrics
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY cpu_percent_total
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )
            cpu_list = [row["cpu_percent_total"] for row in cpu_values]
            cpu_p95 = cpu_list[int(len(cpu_list) * 0.95)] if cpu_list else 0

            # Count conversion activity from activity_events
            conv_rows = await conn.execute_fetchall(
                """
                SELECT COUNT(*) as count
                FROM activity_events
                WHERE event_type IN ('bulk_start', 'bulk_end')
                  AND timestamp >= ? AND timestamp < ?
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )
            files_converted = conv_rows[0]["count"] if conv_rows else 0

            # Count user HTTP requests (approximation from activity_events)
            req_rows = await conn.execute_fetchall(
                """
                SELECT COUNT(*) as count
                FROM activity_events
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )
            user_requests = req_rows[0]["count"] if req_rows else 0

            # I/O rates from system_metrics
            io_rows = await conn.execute_fetchall(
                """
                SELECT
                    AVG(io_read_bytes) as io_read_avg,
                    AVG(io_write_bytes) as io_write_avg
                FROM system_metrics
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )
            io_read = (
                io_rows[0]["io_read_avg"]
                if io_rows and io_rows[0]["io_read_avg"]
                else 0
            )
            io_write = (
                io_rows[0]["io_write_avg"]
                if io_rows and io_rows[0]["io_write_avg"]
                else 0
            )

            # Insert aggregated row
            await conn.execute(
                """
                INSERT INTO auto_metrics
                (hour_bucket, day_of_week, cpu_avg, cpu_p95, memory_avg,
                 memory_peak, active_conversions_avg, files_converted,
                 conversion_throughput, io_read_rate_avg, io_write_rate_avg,
                 user_request_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bucket,
                    dow,
                    r["cpu_avg"],
                    cpu_p95,
                    r["memory_avg"],
                    r["memory_peak"],
                    0,  # active_conversions_avg — enhanced in later version
                    files_converted,
                    files_converted / 60.0,  # rough throughput (files/min)
                    io_read,
                    io_write,
                    user_requests,
                ),
            )
            await conn.commit()

            log.info(
                "auto_metrics_aggregated",
                hour_bucket=bucket,
                cpu_avg=round(r["cpu_avg"], 1),
                cpu_p95=round(cpu_p95, 1),
                memory_avg=round(r["memory_avg"], 1),
                samples=r["sample_count"],
            )

    except Exception as e:
        log.error("auto_metrics_aggregation_failed", error=str(e))


async def purge_old_auto_metrics():
    """Delete auto_metrics rows older than retention setting.

    Called by the daily maintenance job at 03:00.
    """
    retention_days = int(await get_preference("auto_metrics_retention_days") or 30)
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

    try:
        async with get_db() as conn:
            cursor = await conn.execute(
                "DELETE FROM auto_metrics WHERE created_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            await conn.commit()

            # Also purge auto_conversion_runs
            cursor2 = await conn.execute(
                "DELETE FROM auto_conversion_runs WHERE started_at < ?",
                (cutoff,),
            )
            deleted_runs = cursor2.rowcount
            await conn.commit()

            if deleted > 0 or deleted_runs > 0:
                log.info(
                    "auto_metrics_purged",
                    metrics_deleted=deleted,
                    runs_deleted=deleted_runs,
                    retention_days=retention_days,
                )

    except Exception as e:
        log.error("auto_metrics_purge_failed", error=str(e))
