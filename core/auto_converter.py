"""Intelligent auto-conversion engine.

Decides whether, when, and how aggressively to convert files discovered
by the lifecycle scanner. Uses real-time system metrics and historical
usage patterns to make conservative, self-tuning decisions.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
import psutil
import structlog

from core.database import get_preference, get_db_path

logger = structlog.get_logger(__name__)


class AutoConvertDecision:
    """Result of the decision engine — what to do with discovered files."""

    def __init__(
        self,
        should_convert: bool,
        mode: str,
        workers: int,
        batch_size: int,
        reason: str,
        deferred_until: Optional[str] = None,
        metrics_snapshot: Optional[dict] = None,
    ):
        self.should_convert = should_convert
        self.mode = mode
        self.workers = workers
        self.batch_size = batch_size
        self.reason = reason
        self.deferred_until = deferred_until
        self.metrics_snapshot = metrics_snapshot


class AutoConversionEngine:
    """Main engine class. One instance per application lifetime."""

    def __init__(self):
        self._mode_override: Optional[str] = None
        self._override_expiry: Optional[datetime] = None
        self._last_decision: Optional[AutoConvertDecision] = None

    # ── Public API ──────────────────────────────────────────────

    async def on_scan_complete(
        self,
        scan_run_id: str,
        new_files: int,
        modified_files: int,
    ) -> AutoConvertDecision:
        """Called by lifecycle scanner after a scan cycle completes.

        Returns a decision about whether/how to convert discovered files.
        If should_convert is True, the caller is responsible for executing
        the conversion (creating a BulkJob).
        """
        total_discovered = new_files + modified_files

        if total_discovered == 0:
            return AutoConvertDecision(
                should_convert=False,
                mode="off",
                workers=0,
                batch_size=0,
                reason="No new or modified files discovered",
            )

        mode = await self._get_effective_mode()

        if mode == "off":
            return AutoConvertDecision(
                should_convert=False,
                mode="off",
                workers=0,
                batch_size=0,
                reason=f"Auto-conversion is off. {total_discovered} files discovered but not converted.",
            )

        metrics = self._get_current_metrics()
        hist = await self._get_historical_context()
        workers = await self._decide_workers(metrics, hist)
        batch_size = await self._decide_batch_size(total_discovered, metrics, hist)

        if mode == "scheduled":
            in_window = await self._is_in_conversion_window(hist)
            if not in_window:
                next_window = await self._next_window_start(hist)
                decision = AutoConvertDecision(
                    should_convert=False,
                    mode="scheduled",
                    workers=workers,
                    batch_size=batch_size,
                    reason=f"{total_discovered} files discovered. Deferred to next conversion window ({next_window}).",
                    deferred_until=next_window,
                    metrics_snapshot=metrics if await self._should_log_metrics() else None,
                )
                await self._log_decision(decision, scan_run_id, total_discovered)
                self._last_decision = decision
                return decision

        reason = self._build_reason(
            mode=mode,
            total=total_discovered,
            workers=workers,
            batch_size=batch_size,
            metrics=metrics,
            hist=hist,
        )

        decision = AutoConvertDecision(
            should_convert=True,
            mode=mode,
            workers=workers,
            batch_size=batch_size,
            reason=reason,
            metrics_snapshot=metrics if await self._should_log_metrics() else None,
        )

        await self._log_decision(decision, scan_run_id, total_discovered)
        self._last_decision = decision
        return decision

    def set_mode_override(self, mode: str, duration_minutes: int = 60):
        """Set a temporary mode override from the Status page."""
        valid = {"off", "immediate", "queued", "scheduled"}
        if mode not in valid:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid}")
        self._mode_override = mode
        self._override_expiry = datetime.now() + timedelta(minutes=duration_minutes)
        logger.info(
            "auto_convert_mode_override_set",
            override_mode=mode,
            expires_at=self._override_expiry.isoformat(),
            duration_minutes=duration_minutes,
        )

    def clear_mode_override(self):
        """Clear any active mode override."""
        was = self._mode_override
        self._mode_override = None
        self._override_expiry = None
        logger.info(
            "auto_convert_mode_override_cleared",
            previous_mode=was,
        )

    def get_status(self) -> dict:
        """Return current engine status for API/UI."""
        return {
            "mode_override": self._mode_override,
            "override_expiry": self._override_expiry.isoformat() if self._override_expiry else None,
            "override_active": self._is_override_active(),
            "last_decision": {
                "should_convert": self._last_decision.should_convert,
                "mode": self._last_decision.mode,
                "workers": self._last_decision.workers,
                "batch_size": self._last_decision.batch_size,
                "reason": self._last_decision.reason,
            } if self._last_decision else None,
        }

    # ── Private: Mode Resolution ───────────────────────────────

    def _is_override_active(self) -> bool:
        if self._mode_override is None:
            return False
        if self._override_expiry and datetime.now() > self._override_expiry:
            self._mode_override = None
            self._override_expiry = None
            return False
        return True

    async def _get_effective_mode(self) -> str:
        if self._is_override_active():
            return self._mode_override
        return await get_preference("auto_convert_mode") or "off"

    # ── Private: System Metrics ────────────────────────────────

    def _get_current_metrics(self) -> dict:
        """Snapshot current system state via psutil."""
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        now = datetime.now()

        result = {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_available_mb": mem.available / (1024 * 1024),
            "hour": now.hour,
            "day_of_week": now.weekday(),
            "timestamp": now.isoformat(),
        }

        try:
            load_1, load_5, load_15 = psutil.getloadavg()
            result["load_1m"] = load_1
            result["load_5m"] = load_5
            result["load_15m"] = load_15
        except (AttributeError, OSError):
            # getloadavg not available on all platforms
            result["load_1m"] = 0
            result["load_5m"] = 0
            result["load_15m"] = 0

        return result

    # ── Private: Historical Context ────────────────────────────

    async def _get_historical_context(self) -> dict:
        """Query auto_metrics for historical patterns matching current time."""
        now = datetime.now()
        hour = now.hour
        dow = now.weekday()

        try:
            async with aiosqlite.connect(get_db_path()) as conn:
                conn.row_factory = aiosqlite.Row

                rows = await conn.execute_fetchall(
                    """
                    SELECT
                        AVG(cpu_avg) as cpu_avg,
                        AVG(cpu_p95) as cpu_p95,
                        AVG(memory_avg) as memory_avg,
                        AVG(memory_peak) as memory_peak,
                        AVG(active_conversions_avg) as active_conversions_avg,
                        AVG(conversion_throughput) as conversion_throughput,
                        AVG(user_request_count) as user_request_count,
                        COUNT(*) as sample_count
                    FROM auto_metrics
                    WHERE day_of_week = ?
                      AND cast(strftime('%H', hour_bucket) as integer) = ?
                    """,
                    (dow, hour),
                )

                if rows and rows[0] and rows[0]["sample_count"] > 0:
                    r = rows[0]
                    return {
                        "cpu_avg": r["cpu_avg"],
                        "cpu_p95": r["cpu_p95"],
                        "memory_avg": r["memory_avg"],
                        "memory_peak": r["memory_peak"],
                        "active_conversions_avg": r["active_conversions_avg"],
                        "conversion_throughput": r["conversion_throughput"],
                        "user_request_count": r["user_request_count"],
                        "sample_count": r["sample_count"],
                        "has_history": True,
                    }

        except Exception as e:
            logger.warning("auto_convert_historical_query_failed", error=str(e))

        return {
            "has_history": False,
            "sample_count": 0,
        }

    # ── Private: Worker Decision ───────────────────────────────

    async def _decide_workers(self, metrics: dict, hist: dict) -> int:
        """Decide how many workers to use."""
        pref = await get_preference("auto_convert_workers") or "auto"

        if pref != "auto":
            return int(pref)

        conservative_factor = float(
            await get_preference("auto_convert_conservative_factor") or 0.7
        )

        cpu_now = metrics["cpu_percent"]
        cpu_count = psutil.cpu_count() or 4

        headroom = max(0, 100 - cpu_now)

        if hist.get("has_history"):
            hist_cpu = hist["cpu_avg"]
            effective_load = max(cpu_now, hist_cpu)
            headroom = max(0, 100 - effective_load)

        bh_start = int((await get_preference("auto_convert_business_hours_start") or "06:00").split(":")[0])
        bh_end = int((await get_preference("auto_convert_business_hours_end") or "18:00").split(":")[0])
        in_business = bh_start <= metrics["hour"] < bh_end and metrics["day_of_week"] < 5

        if in_business:
            conservative_factor *= 0.7

        raw_workers = max(1, int((headroom * conservative_factor) / 15))
        max_workers = min(cpu_count, 8)

        return min(raw_workers, max_workers)

    # ── Private: Batch Size Decision ───────────────────────────

    async def _decide_batch_size(
        self, total_discovered: int, metrics: dict, hist: dict
    ) -> int:
        """Decide how many files to convert in this batch. 0 = all."""
        pref = await get_preference("auto_convert_batch_size") or "auto"

        if pref == "unlimited":
            return 0
        if pref != "auto":
            return min(int(pref), total_discovered)

        conservative_factor = float(
            await get_preference("auto_convert_conservative_factor") or 0.7
        )

        bh_start = int((await get_preference("auto_convert_business_hours_start") or "06:00").split(":")[0])
        bh_end = int((await get_preference("auto_convert_business_hours_end") or "18:00").split(":")[0])
        hour = metrics["hour"]
        dow = metrics["day_of_week"]
        in_business = bh_start <= hour < bh_end and dow < 5

        in_dead_hours = 0 <= hour < 5

        low_activity = True
        if hist.get("has_history"):
            low_activity = (hist.get("user_request_count", 0) or 0) < 10

        if in_dead_hours and low_activity:
            base = min(500, total_discovered)
        elif not in_business:
            base = min(250, total_discovered)
        elif in_business and low_activity:
            base = min(100, total_discovered)
        else:
            base = min(50, total_discovered)

        batch = max(1, int(base * conservative_factor))
        return min(batch, total_discovered)

    # ── Private: Schedule Windows ──────────────────────────────

    async def _is_in_conversion_window(self, hist: dict) -> bool:
        """Check if the current time is within a conversion window."""
        windows_json = await get_preference("auto_convert_schedule_windows") or ""

        if windows_json.strip():
            return self._check_explicit_windows(windows_json)
        else:
            return self._check_auto_window(hist)

    def _check_explicit_windows(self, windows_json: str) -> bool:
        try:
            windows = json.loads(windows_json)
        except json.JSONDecodeError:
            logger.warning("auto_convert_invalid_schedule_json", raw=windows_json)
            return False

        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_dow = now.weekday()

        for w in windows:
            start = w.get("start", "00:00")
            end = w.get("end", "23:59")
            days = w.get("days", [0, 1, 2, 3, 4, 5, 6])

            if current_dow in days and start <= current_time < end:
                return True

        return False

    def _check_auto_window(self, hist: dict) -> bool:
        """Auto-detect if current time is a good conversion window."""
        now = datetime.now()
        hour = now.hour

        if 0 <= hour < 5:
            return True

        if hist.get("has_history"):
            user_requests = hist.get("user_request_count", 0) or 0
            cpu_avg = hist.get("cpu_avg", 50) or 50

            if user_requests < 5 and cpu_avg < 30:
                return True

        return False

    async def _next_window_start(self, hist: dict) -> Optional[str]:
        """Estimate when the next conversion window opens."""
        windows_json = await get_preference("auto_convert_schedule_windows") or ""

        if windows_json.strip():
            try:
                windows = json.loads(windows_json)
                now = datetime.now()
                for w in windows:
                    start_h, start_m = map(int, w.get("start", "00:00").split(":"))
                    for day_offset in range(7):
                        candidate = now.replace(
                            hour=start_h, minute=start_m, second=0
                        ) + timedelta(days=day_offset)
                        if candidate > now and candidate.weekday() in w.get(
                            "days", [0, 1, 2, 3, 4, 5, 6]
                        ):
                            return candidate.strftime("%Y-%m-%d %H:%M")
            except (json.JSONDecodeError, ValueError):
                pass

        now = datetime.now()
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0
        )
        return tomorrow_midnight.strftime("%Y-%m-%d %H:%M")

    # ── Private: Decision Reasoning ────────────────────────────

    def _build_reason(
        self,
        mode: str,
        total: int,
        workers: int,
        batch_size: int,
        metrics: dict,
        hist: dict,
    ) -> str:
        parts = []
        parts.append(f"Mode={mode}")
        parts.append(f"{total} files discovered")
        parts.append(f"CPU now={metrics['cpu_percent']:.1f}%")

        if hist.get("has_history"):
            parts.append(f"CPU historical avg={hist['cpu_avg']:.1f}%")
            parts.append(f"samples={hist['sample_count']}")
        else:
            parts.append("no historical data yet")

        hour = metrics["hour"]
        dow = metrics["day_of_week"]
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        parts.append(f"{day_names[dow]} {hour:02d}:00")

        in_business = 6 <= hour < 18 and dow < 5
        parts.append("business hours" if in_business else "off hours")

        parts.append(f"workers={workers}")
        parts.append(f"batch={batch_size if batch_size > 0 else 'all'}")

        return " | ".join(parts)

    # ── Private: Decision Logging ──────────────────────────────

    async def _should_log_metrics(self) -> bool:
        level = await get_preference("auto_convert_decision_log_level") or "elevated"
        return level == "developer"

    async def _log_decision(
        self, decision: AutoConvertDecision, scan_run_id: str, files_discovered: int = 0
    ):
        """Log the decision at the configured verbosity level."""
        pref_level = await get_preference("auto_convert_decision_log_level") or "elevated"

        log_data = {
            "scan_run_id": scan_run_id,
            "decision_mode": decision.mode,
            "should_convert": decision.should_convert,
            "workers": decision.workers,
            "batch_size": decision.batch_size,
        }

        if pref_level in ("elevated", "developer"):
            now = datetime.now()
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            log_data.update({
                "reason": decision.reason,
                "hour": now.hour,
                "day": now.weekday(),
                "day_name": day_names[now.weekday()],
                "period": (
                    "business"
                    if 6 <= now.hour < 18 and now.weekday() < 5
                    else "off_hours"
                ),
                "files_discovered": files_discovered,
            })

        if pref_level == "developer" and decision.metrics_snapshot:
            log_data["metrics_snapshot"] = decision.metrics_snapshot

        if decision.should_convert:
            logger.info("auto_convert_decision", **log_data)
        else:
            logger.debug("auto_convert_decision", **log_data)

        # Persist to auto_conversion_runs table
        try:
            ms = decision.metrics_snapshot or {}
            async with aiosqlite.connect(get_db_path()) as conn:
                await conn.execute(
                    """
                    INSERT INTO auto_conversion_runs
                    (scan_run_id, mode, was_override, files_discovered,
                     batch_size_chosen, workers_chosen, cpu_at_decision,
                     memory_at_decision, cpu_hist_avg, reason, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_run_id,
                        decision.mode,
                        1 if self._is_override_active() else 0,
                        files_discovered,
                        decision.batch_size,
                        decision.workers,
                        ms.get("cpu_percent"),
                        ms.get("memory_percent"),
                        None,
                        decision.reason,
                        "pending" if decision.should_convert else (
                            "deferred" if decision.deferred_until else "skipped"
                        ),
                    ),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("auto_convert_run_insert_failed", error=str(e))


# ── Module-level singleton ─────────────────────────────────────

_engine: Optional[AutoConversionEngine] = None


def get_auto_conversion_engine() -> AutoConversionEngine:
    """Return the module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = AutoConversionEngine()
    return _engine
