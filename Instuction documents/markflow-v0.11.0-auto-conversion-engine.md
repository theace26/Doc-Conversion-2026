# MarkFlow v0.11.0 Patch: Intelligent Auto-Conversion Engine

> **Patch target:** New files + modifications to existing scheduler, settings, status, and metrics modules  
> **Purpose:** When the lifecycle scanner finds new or modified files in the source share, automatically convert them using an intelligent, self-tuning engine that adapts its behavior based on real-time system load and historical usage patterns.  
> **Grounded in:** CLAUDE.md as of v0.10.1. All file paths, table names, page names, route patterns, CSS class names, and JS conventions match the running codebase.

---

## 1. What This Patch Does

Currently, the lifecycle scanner (v0.8.5) detects new, modified, moved, and deleted files in the source share every 15 minutes during business hours. It updates the `bulk_files` table but does **not** trigger conversion — files sit in `pending` status until a user manually starts a bulk job.

This patch adds an **intelligent auto-conversion engine** that:

1. **Three selectable conversion modes:**
   - **Immediate** — converts files within the same scan cycle that discovers them
   - **Queued** — scanner logs discoveries, a separate background task picks them up shortly after
   - **Scheduled** — conversion batches run only during defined time windows (user-set or auto-determined)

2. **Dynamic worker scaling** — automatically adjusts worker count based on real-time CPU/memory load and historical averages for the current hour/day. Always adjusts conservatively.

3. **Intelligent batch sizing** — when the scanner finds hundreds of new files, the engine decides how many to process per batch based on system load, time of day, and historical throughput.

4. **Historical metrics learning** — collects time-series system data (CPU, memory, conversion throughput, access patterns by hour) in both SQLite (for queries) and structured JSON logs (for Grafana/Loki). The "auto" modes use this data to make informed, conservative decisions.

5. **Decision logging** — every auto-conversion decision logs its full reasoning in Grafana-ready structured JSON. Logging verbosity is selectable in Settings.

6. **Status page override** — per-scan-cycle mode override on the Status page, so the user can temporarily switch modes without changing the global setting.

---

## 2. Architecture Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Engine module | New `core/auto_converter.py` | Clean separation from lifecycle scanner and bulk worker |
| Metrics storage | SQLite `auto_metrics` table + `structlog` JSON for Grafana | SQLite for queries/learning, structured log for Grafana/Loki ingestion |
| Decision logging | Selectable: Normal/Elevated/Developer | Consistent with v0.9.5 three-tier logging system |
| Worker scaling | Reuse existing `BulkJob` + `BulkWorker` infrastructure | No new worker infrastructure — auto-conversion creates bulk jobs programmatically |
| Scheduling | APScheduler (already in `core/scheduler.py`) | Already handles lifecycle scans; add auto-conversion as a linked job |
| Mode override | In-memory state on Status page | Ephemeral by design — reverts to Settings value on container restart |
| Time windows | Cron-like hour ranges stored as preference JSON | Simple, no new dependency, parseable by both Python and JS |

**Architecture rules followed:**
- No SPA — vanilla HTML + fetch calls
- No new Python dependencies (APScheduler, psutil, structlog all already installed)
- No localStorage (mode override is server-side in-memory)
- structlog for all new logging
- Reuses existing `core/bulk_worker.py`, `core/bulk_scanner.py`, `core/metrics_collector.py`
- All new preferences go in `_PREFERENCE_SCHEMA` in `core/database.py`

---

## 3. Data Model

### 3.1 New SQLite Table: `auto_metrics`

This table stores per-hour aggregated system metrics used by the auto-conversion decision engine to learn historical patterns. It is **separate** from the existing `system_metrics` table (which stores raw 30-second samples for the Resources page).

```sql
CREATE TABLE IF NOT EXISTS auto_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_bucket TEXT NOT NULL,          -- ISO format: '2026-03-27T14:00:00'
    day_of_week INTEGER NOT NULL,       -- 0=Monday, 6=Sunday (Python weekday())
    cpu_avg REAL NOT NULL,              -- Average CPU% for this hour
    cpu_p95 REAL NOT NULL,              -- 95th percentile CPU% for this hour
    memory_avg REAL NOT NULL,           -- Average memory% for this hour
    memory_peak REAL NOT NULL,          -- Peak memory% for this hour
    active_conversions_avg REAL NOT NULL DEFAULT 0,  -- Avg concurrent conversions
    files_converted INTEGER NOT NULL DEFAULT 0,       -- Total files converted in this hour
    conversion_throughput REAL NOT NULL DEFAULT 0,    -- Files per minute average
    io_read_rate_avg REAL NOT NULL DEFAULT 0,         -- Avg I/O read bytes/sec
    io_write_rate_avg REAL NOT NULL DEFAULT 0,        -- Avg I/O write bytes/sec
    user_request_count INTEGER NOT NULL DEFAULT 0,    -- HTTP requests from users this hour
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_metrics_bucket
    ON auto_metrics(hour_bucket);

CREATE INDEX IF NOT EXISTS idx_auto_metrics_dow_hour
    ON auto_metrics(day_of_week, cast(strftime('%H', hour_bucket) as integer));
```

**Aggregation strategy:** Every hour, the engine aggregates the raw `system_metrics` samples from the past hour into a single `auto_metrics` row. This gives the decision engine compact, queryable historical data without touching the high-frequency raw table.

**Retention:** Configurable via `auto_metrics_retention_days` preference (default 30). Purged by the existing daily maintenance job at 03:00.

### 3.2 New SQLite Table: `auto_conversion_runs`

Tracks each auto-conversion decision and execution for auditability.

```sql
CREATE TABLE IF NOT EXISTS auto_conversion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id TEXT,                   -- Links to scan_runs.run_id that triggered this
    mode TEXT NOT NULL,                 -- 'immediate', 'queued', 'scheduled'
    was_override INTEGER NOT NULL DEFAULT 0,  -- 1 if mode was a status-page override
    files_discovered INTEGER NOT NULL DEFAULT 0,
    files_queued INTEGER NOT NULL DEFAULT 0,
    batch_size_chosen INTEGER NOT NULL DEFAULT 0,
    workers_chosen INTEGER NOT NULL DEFAULT 0,
    cpu_at_decision REAL,
    memory_at_decision REAL,
    cpu_hist_avg REAL,                  -- Historical avg CPU for this hour+day
    reason TEXT,                        -- Human-readable decision reasoning
    bulk_job_id TEXT,                   -- Links to bulk_jobs.id if a job was created
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending'  -- pending, running, completed, skipped, deferred
);

CREATE INDEX IF NOT EXISTS idx_auto_runs_status
    ON auto_conversion_runs(status);

CREATE INDEX IF NOT EXISTS idx_auto_runs_started
    ON auto_conversion_runs(started_at);
```

### 3.3 New Preference Keys

Add these to `_PREFERENCE_SCHEMA` in `core/database.py`:

```python
# ── Auto-Conversion ──
"auto_convert_mode": {
    "type": "select",
    "default": "off",
    "options": ["off", "immediate", "queued", "scheduled"],
    "label": "Auto-Conversion Mode",
    "description": "How to handle new/modified files found by the lifecycle scanner. Off = detect only, no conversion.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_convert_workers": {
    "type": "select",
    "default": "auto",
    "options": ["auto", "1", "2", "3", "4", "6", "8"],
    "label": "Auto-Conversion Workers",
    "description": "Number of parallel conversion workers for auto-conversion jobs. Auto dynamically adjusts based on system load.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_convert_batch_size": {
    "type": "select",
    "default": "auto",
    "options": ["auto", "25", "50", "100", "250", "500", "unlimited"],
    "label": "Max Batch Size",
    "description": "Maximum files to convert per auto-conversion run. Auto adjusts based on system load and time of day.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_convert_schedule_windows": {
    "type": "text",
    "default": "",
    "label": "Scheduled Conversion Windows",
    "description": "Time windows for scheduled mode (JSON). Example: [{\"start\": \"00:00\", \"end\": \"05:00\", \"days\": [0,1,2,3,4]}]. Leave empty for auto-detection based on historical low-usage periods.",
    "section": "auto_conversion",
    "system_level": True,
    "validate": "_validate_schedule_windows",
},
"auto_convert_decision_log_level": {
    "type": "select",
    "default": "elevated",
    "options": ["normal", "elevated", "developer"],
    "label": "Decision Logging Level",
    "description": "How much detail to log about auto-conversion decisions. Elevated logs full reasoning. Developer adds raw metric snapshots.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_metrics_retention_days": {
    "type": "number",
    "default": 30,
    "min": 7,
    "max": 365,
    "label": "Metrics Retention (Days)",
    "description": "How long to keep historical system metrics used for auto-conversion decisions. Longer retention = better pattern learning.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_convert_business_hours_start": {
    "type": "select",
    "default": "06:00",
    "options": ["00:00","01:00","02:00","03:00","04:00","05:00","06:00","07:00","08:00","09:00","10:00","11:00","12:00"],
    "label": "Business Hours Start",
    "description": "Start of business hours. Auto-conversion throttles during this window.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_convert_business_hours_end": {
    "type": "select",
    "default": "18:00",
    "options": ["12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00","21:00","22:00","23:00"],
    "label": "Business Hours End",
    "description": "End of business hours. After this, auto-conversion can be more aggressive.",
    "section": "auto_conversion",
    "system_level": True,
},
"auto_convert_conservative_factor": {
    "type": "range",
    "default": 0.7,
    "min": 0.3,
    "max": 1.0,
    "step": 0.05,
    "label": "Conservatism Factor",
    "description": "How cautiously auto-conversion uses resources. 0.3 = very conservative (uses ≤30% of available headroom). 1.0 = full utilization. Default 0.7 is moderately conservative.",
    "section": "auto_conversion",
    "system_level": True,
},
```

**Add all `auto_convert_*` and `auto_metrics_*` keys to `_SYSTEM_PREF_KEYS`** so they require Manager role.

---

## 4. Core Engine: `core/auto_converter.py`

This is the brain of the system. It is called by the lifecycle scanner after a scan completes and decides **whether**, **when**, and **how aggressively** to convert discovered files.

### 4.1 Module Structure

```python
"""Intelligent auto-conversion engine.

Decides whether, when, and how aggressively to convert files discovered
by the lifecycle scanner. Uses real-time system metrics and historical
usage patterns to make conservative, self-tuning decisions.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

import psutil
import structlog

from core.database import get_preference, get_db_path

logger = structlog.get_logger(__name__)


class AutoConvertDecision:
    """Result of the decision engine — what to do with discovered files."""

    def __init__(
        self,
        should_convert: bool,
        mode: str,                    # 'immediate', 'queued', 'scheduled', 'off'
        workers: int,
        batch_size: int,              # 0 = all discovered files
        reason: str,                  # Human-readable reasoning
        deferred_until: Optional[datetime] = None,  # For scheduled mode
        metrics_snapshot: Optional[dict] = None,     # Raw metrics at decision time
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
        self._mode_override: Optional[str] = None  # Status page ephemeral override
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

        # 1. Determine effective mode (override or preference)
        mode = await self._get_effective_mode()

        if mode == "off":
            return AutoConvertDecision(
                should_convert=False,
                mode="off",
                workers=0,
                batch_size=0,
                reason=f"Auto-conversion is off. {total_discovered} files discovered but not converted.",
            )

        # 2. Get current system state
        metrics = self._get_current_metrics()

        # 3. Get historical context
        hist = await self._get_historical_context()

        # 4. Determine workers
        workers = await self._decide_workers(metrics, hist)

        # 5. Determine batch size
        batch_size = await self._decide_batch_size(
            total_discovered, metrics, hist
        )

        # 6. Mode-specific logic
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

        # 7. Build the decision
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

        # 8. Log the decision
        await self._log_decision(decision, scan_run_id, total_discovered)

        self._last_decision = decision
        return decision

    def set_mode_override(self, mode: str, duration_minutes: int = 60):
        """Set a temporary mode override from the Status page.

        Expires after duration_minutes or on container restart.
        """
        valid = {"off", "immediate", "queued", "scheduled"}
        if mode not in valid:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid}")
        self._mode_override = mode
        self._override_expiry = datetime.now() + timedelta(minutes=duration_minutes)
        logger.info(
            "auto_convert_mode_override_set",
            event="auto_convert_mode_override_set",
            mode=mode,
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
            event="auto_convert_mode_override_cleared",
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
        load_1, load_5, load_15 = psutil.getloadavg()
        now = datetime.now()

        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_available_mb": mem.available / (1024 * 1024),
            "load_1m": load_1,
            "load_5m": load_5,
            "load_15m": load_15,
            "hour": now.hour,
            "day_of_week": now.weekday(),
            "timestamp": now.isoformat(),
        }

    # ── Private: Historical Context ────────────────────────────

    async def _get_historical_context(self) -> dict:
        """Query auto_metrics for historical patterns matching current time.

        Returns averages for this hour+day across available history.
        """
        import aiosqlite

        now = datetime.now()
        hour = now.hour
        dow = now.weekday()

        try:
            async with aiosqlite.connect(get_db_path()) as conn:
                conn.row_factory = aiosqlite.Row

                # Get average metrics for this hour + day of week
                row = await conn.execute_fetchall(
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

                if row and row[0] and row[0]["sample_count"] > 0:
                    r = row[0]
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
        """Decide how many workers to use.

        If preference is a fixed number, use it.
        If 'auto', calculate based on current load + historical context.
        """
        pref = await get_preference("auto_convert_workers") or "auto"

        if pref != "auto":
            return int(pref)

        conservative_factor = float(
            await get_preference("auto_convert_conservative_factor") or 0.7
        )

        cpu_now = metrics["cpu_percent"]
        cpu_count = psutil.cpu_count() or 4

        # Base: available CPU headroom
        headroom = max(0, 100 - cpu_now)

        # If we have history, factor it in
        if hist.get("has_history"):
            hist_cpu = hist["cpu_avg"]
            # Use the worse (higher) of current and historical as our baseline
            effective_load = max(cpu_now, hist_cpu)
            headroom = max(0, 100 - effective_load)

        # Determine if we're in business hours
        bh_start = int((await get_preference("auto_convert_business_hours_start") or "06:00").split(":")[0])
        bh_end = int((await get_preference("auto_convert_business_hours_end") or "18:00").split(":")[0])
        in_business = bh_start <= metrics["hour"] < bh_end and metrics["day_of_week"] < 5

        # During business hours: more conservative
        if in_business:
            conservative_factor *= 0.7  # Stack additional conservatism

        # Worker count: roughly 1 worker per 15% available headroom, capped
        raw_workers = max(1, int((headroom * conservative_factor) / 15))
        max_workers = min(cpu_count, 8)  # Never exceed core count or 8

        workers = min(raw_workers, max_workers)

        return workers

    # ── Private: Batch Size Decision ───────────────────────────

    async def _decide_batch_size(
        self, total_discovered: int, metrics: dict, hist: dict
    ) -> int:
        """Decide how many files to convert in this batch.

        If preference is fixed, use it. If 'auto', calculate.
        Returns 0 to mean 'all discovered files'.
        """
        pref = await get_preference("auto_convert_batch_size") or "auto"

        if pref == "unlimited":
            return 0  # Convert all
        if pref != "auto":
            return min(int(pref), total_discovered)

        conservative_factor = float(
            await get_preference("auto_convert_conservative_factor") or 0.7
        )

        # Determine time context
        bh_start = int((await get_preference("auto_convert_business_hours_start") or "06:00").split(":")[0])
        bh_end = int((await get_preference("auto_convert_business_hours_end") or "18:00").split(":")[0])
        hour = metrics["hour"]
        dow = metrics["day_of_week"]
        in_business = bh_start <= hour < bh_end and dow < 5

        # Dead hours (very low activity expected)
        dead_start = 0  # Midnight
        dead_end = 5    # 5 AM
        in_dead_hours = dead_start <= hour < dead_end

        # Historical user activity check
        low_activity = True
        if hist.get("has_history"):
            # If historical user request count for this hour is > 10, treat as active
            low_activity = (hist.get("user_request_count", 0) or 0) < 10

        # Base batch size
        if in_dead_hours and low_activity:
            # Dead hours with verified low historical activity: aggressive
            base = min(500, total_discovered)
        elif not in_business:
            # After hours but not dead hours: moderate
            base = min(250, total_discovered)
        elif in_business and low_activity:
            # Business hours but historically quiet: moderate-conservative
            base = min(100, total_discovered)
        else:
            # Business hours, active usage: conservative
            base = min(50, total_discovered)

        # Apply conservatism factor
        batch = max(1, int(base * conservative_factor))

        return min(batch, total_discovered)

    # ── Private: Schedule Windows ──────────────────────────────

    async def _is_in_conversion_window(self, hist: dict) -> bool:
        """Check if the current time is within a conversion window.

        If explicit windows are configured, use those.
        If empty, auto-detect based on historical low-usage periods.
        """
        windows_json = await get_preference("auto_convert_schedule_windows") or ""

        if windows_json.strip():
            return self._check_explicit_windows(windows_json)
        else:
            return self._check_auto_window(hist)

    def _check_explicit_windows(self, windows_json: str) -> bool:
        """Check if current time matches any explicit window."""
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
        """Auto-detect if current time is a good conversion window.

        Uses historical data to identify low-usage periods.
        Fallback: dead hours (midnight-5am) are always a window.
        """
        now = datetime.now()
        hour = now.hour

        # Fallback: dead hours are always a window
        if 0 <= hour < 5:
            return True

        # If we have history, check if this hour is historically quiet
        if hist.get("has_history"):
            user_requests = hist.get("user_request_count", 0) or 0
            cpu_avg = hist.get("cpu_avg", 50) or 50

            # "Quiet" = fewer than 5 user requests and CPU below 30%
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

        # Fallback: next midnight
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
        """Build a human-readable reasoning string."""
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

        # Business hours check (use defaults for reason string)
        in_business = 6 <= hour < 18 and dow < 5
        parts.append("business hours" if in_business else "off hours")

        parts.append(f"workers={workers}")
        parts.append(f"batch={batch_size if batch_size > 0 else 'all'}")

        return " | ".join(parts)

    # ── Private: Decision Logging ──────────────────────────────

    async def _should_log_metrics(self) -> bool:
        """Check if raw metric snapshots should be included in logs."""
        level = await get_preference("auto_convert_decision_log_level") or "elevated"
        return level == "developer"

    async def _log_decision(
        self, decision: AutoConvertDecision, scan_run_id: str, files_discovered: int = 0
    ):
        """Log the decision at the configured verbosity level.

        Uses structured fields designed for Grafana/Loki query and dashboard.
        Field names are consistent and queryable:
          event, mode, workers, batch_size, cpu_current, cpu_hist_avg,
          memory_current, hour, day, day_name, period, files_discovered,
          reason, scan_run_id
        """
        pref_level = await get_preference("auto_convert_decision_log_level") or "elevated"

        # ── Structured fields for Grafana ──
        log_data = {
            "event": "auto_convert_decision",
            "scan_run_id": scan_run_id,
            "mode": decision.mode,
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
            logger.info(**log_data)
        else:
            logger.debug(**log_data)

        # ── Persist to auto_conversion_runs table ──
        try:
            import aiosqlite

            async with aiosqlite.connect(get_db_path()) as conn:
                ms = decision.metrics_snapshot or {}
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
                        None,  # cpu_hist_avg filled from hist dict if available
                        decision.reason,
                        "pending" if decision.should_convert else (
                            "deferred" if decision.deferred_until else "skipped"
                        ),
                    ),
                )
                await conn.commit()
        except Exception as e:
            # Fire-and-forget — never disrupt the conversion pipeline
            logger.warning("auto_convert_run_insert_failed", error=str(e))


# ── Module-level singleton ─────────────────────────────────────

_engine: Optional[AutoConversionEngine] = None


def get_auto_conversion_engine() -> AutoConversionEngine:
    """Return the module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = AutoConversionEngine()
    return _engine
```

### 4.2 Key Design Principles

1. **Conservative by default.** Every calculation applies the conservatism factor. Business hours stack an additional 30% reduction on top.

2. **Historical data is optional.** The engine works from day one with no history — it falls back to reasonable defaults based on time of day and current CPU. As data accumulates, decisions get smarter.

3. **Fire-and-forget logging.** Decision persistence to `auto_conversion_runs` is wrapped in try/except. A failed log insert never blocks or crashes a conversion.

4. **Grafana-ready field names.** Every log entry uses consistent, flat key names (`event`, `mode`, `workers`, `cpu_current`, `hour`, `day_name`, `period`). Grafana dashboards can query these directly without JSON path parsing.

5. **Override is ephemeral.** The Status page mode override lives in-memory only. Container restart resets it. This prevents a forgotten override from silently changing behavior long-term.

---

## 5. Hourly Metrics Aggregator: `core/auto_metrics_aggregator.py`

This module runs once per hour (via APScheduler) and rolls up the raw `system_metrics` samples from the past hour into a single `auto_metrics` row.

```python
"""Hourly aggregator for auto-conversion historical metrics.

Reads raw system_metrics samples from the last hour, computes aggregates,
and inserts one row into auto_metrics. Also tracks conversion activity
and user request counts from activity_events.
"""

import aiosqlite
import structlog
from datetime import datetime, timedelta

from core.database import get_db_path, get_preference

logger = structlog.get_logger(__name__)


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
        async with aiosqlite.connect(get_db_path()) as conn:
            conn.row_factory = aiosqlite.Row

            # Check if already aggregated (idempotent)
            existing = await conn.execute_fetchall(
                "SELECT id FROM auto_metrics WHERE hour_bucket = ?",
                (bucket,),
            )
            if existing:
                return  # Already done

            # Aggregate system_metrics for this hour
            rows = await conn.execute_fetchall(
                """
                SELECT
                    AVG(cpu_percent) as cpu_avg,
                    MAX(cpu_percent) as cpu_max,
                    AVG(memory_percent) as memory_avg,
                    MAX(memory_percent) as memory_peak,
                    COUNT(*) as sample_count
                FROM system_metrics
                WHERE recorded_at >= ? AND recorded_at < ?
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )

            if not rows or rows[0]["sample_count"] == 0:
                logger.debug(
                    "auto_metrics_no_samples",
                    hour_bucket=bucket,
                )
                return

            r = rows[0]

            # Compute p95 CPU in Python (SQLite lacks PERCENTILE_CONT)
            cpu_values = await conn.execute_fetchall(
                """
                SELECT cpu_percent FROM system_metrics
                WHERE recorded_at >= ? AND recorded_at < ?
                ORDER BY cpu_percent
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )
            cpu_list = [row["cpu_percent"] for row in cpu_values]
            cpu_p95 = cpu_list[int(len(cpu_list) * 0.95)] if cpu_list else 0

            # Count conversion activity from activity_events
            conv_rows = await conn.execute_fetchall(
                """
                SELECT COUNT(*) as count
                FROM activity_events
                WHERE event_type IN ('bulk_start', 'bulk_end')
                  AND created_at >= ? AND created_at < ?
                """,
                (hour_start.isoformat(), hour_end.isoformat()),
            )
            files_converted = conv_rows[0]["count"] if conv_rows else 0

            # Count user HTTP requests (approximation from activity_events)
            req_rows = await conn.execute_fetchall(
                """
                SELECT COUNT(*) as count
                FROM activity_events
                WHERE created_at >= ? AND created_at < ?
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
                WHERE recorded_at >= ? AND recorded_at < ?
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

            logger.info(
                "auto_metrics_aggregated",
                event="auto_metrics_aggregated",
                hour_bucket=bucket,
                cpu_avg=round(r["cpu_avg"], 1),
                cpu_p95=round(cpu_p95, 1),
                memory_avg=round(r["memory_avg"], 1),
                samples=r["sample_count"],
            )

    except Exception as e:
        logger.error("auto_metrics_aggregation_failed", error=str(e))


async def purge_old_auto_metrics():
    """Delete auto_metrics rows older than retention setting.

    Called by the daily maintenance job at 03:00.
    """
    retention_days = int(await get_preference("auto_metrics_retention_days") or 30)
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

    try:
        async with aiosqlite.connect(get_db_path()) as conn:
            result = await conn.execute(
                "DELETE FROM auto_metrics WHERE created_at < ?",
                (cutoff,),
            )
            deleted = result.rowcount
            await conn.commit()

            # Also purge auto_conversion_runs
            result2 = await conn.execute(
                "DELETE FROM auto_conversion_runs WHERE started_at < ?",
                (cutoff,),
            )
            deleted_runs = result2.rowcount
            await conn.commit()

            if deleted > 0 or deleted_runs > 0:
                logger.info(
                    "auto_metrics_purged",
                    event="auto_metrics_purged",
                    metrics_deleted=deleted,
                    runs_deleted=deleted_runs,
                    retention_days=retention_days,
                )

    except Exception as e:
        logger.error("auto_metrics_purge_failed", error=str(e))
```

---

## 6. Integration with Lifecycle Scanner

### 6.1 Modify `core/lifecycle_scanner.py`

After the lifecycle scanner completes its scan and has tallied new/modified files, call the auto-conversion engine.

**Find** the end of the `_run_scan()` method (or equivalent) where it logs scan completion and updates `scan_runs` with `status='completed'`. **After** that logging block, add:

```python
# ── Auto-conversion trigger ──
from core.auto_converter import get_auto_conversion_engine

engine = get_auto_conversion_engine()
decision = await engine.on_scan_complete(
    scan_run_id=scan_run_id,
    new_files=new_count,         # Use the variable that tracks newly discovered files
    modified_files=modified_count,  # Use the variable that tracks modified files
)

if decision.should_convert:
    await self._execute_auto_conversion(decision, scan_run_id)
```

**Add** a new method to the `LifecycleScanner` class (or whatever class/function owns the scan loop):

```python
async def _execute_auto_conversion(self, decision, scan_run_id: str):
    """Create and start a bulk job based on the auto-conversion decision.

    Uses the existing BulkJob infrastructure — auto-conversion is just
    a programmatically-created bulk job with specific worker/batch settings.
    """
    from core.bulk_worker import BulkJob

    try:
        # Get the location info from the scanner's existing config.
        # The lifecycle scanner already knows its source_path and output_path
        # from the location/preference that configures it. Use those same values.
        source_path = self._source_path  # or however the scanner stores it
        output_path = self._output_path  # or however the scanner stores it

        if not source_path or not output_path:
            logger.warning(
                "auto_convert_no_paths",
                event="auto_convert_no_paths",
                reason="lifecycle source/output paths not configured",
            )
            return

        # Create a bulk job marked as auto-conversion
        # Use the existing create_bulk_job() or equivalent function
        # that inserts into bulk_jobs table and returns a job_id.
        import uuid
        from core.database import get_db_path
        import aiosqlite

        job_id = str(uuid.uuid4())

        async with aiosqlite.connect(get_db_path()) as conn:
            await conn.execute(
                """
                INSERT INTO bulk_jobs (id, source_path, output_path, status, auto_triggered)
                VALUES (?, ?, ?, 'pending', 1)
                """,
                (job_id, str(source_path), str(output_path)),
            )
            await conn.commit()

        logger.info(
            "auto_convert_job_created",
            event="auto_convert_job_created",
            job_id=job_id,
            mode=decision.mode,
            workers=decision.workers,
            batch_size=decision.batch_size,
            scan_run_id=scan_run_id,
        )

        # Update the auto_conversion_runs record with the bulk_job_id
        try:
            async with aiosqlite.connect(get_db_path()) as conn:
                await conn.execute(
                    """
                    UPDATE auto_conversion_runs
                    SET bulk_job_id = ?, status = 'running'
                    WHERE scan_run_id = ? AND status = 'pending'
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    (job_id, scan_run_id),
                )
                await conn.commit()
        except Exception:
            pass  # Fire-and-forget

        if decision.mode == "immediate":
            # Start conversion immediately in this scan cycle.
            # This blocks the scanner until the batch completes.
            # For immediate mode this is the defined behavior.
            job = BulkJob(
                job_id=job_id,
                source_path=str(source_path),
                output_path=str(output_path),
                worker_count=decision.workers,
                max_files=decision.batch_size if decision.batch_size > 0 else None,
            )
            await job.run()

        elif decision.mode in ("queued", "scheduled"):
            # Start conversion as a background task — scanner moves on
            job = BulkJob(
                job_id=job_id,
                source_path=str(source_path),
                output_path=str(output_path),
                worker_count=decision.workers,
                max_files=decision.batch_size if decision.batch_size > 0 else None,
            )
            asyncio.create_task(job.run())

    except Exception as e:
        logger.error(
            "auto_convert_execution_failed",
            event="auto_convert_execution_failed",
            error=str(e),
            scan_run_id=scan_run_id,
        )
```

**Important implementation notes:**

- The actual variable names for `new_count` and `modified_count` depend on what the existing `_run_scan()` already tracks. The scanner already logs these counts — wire them into the engine call. Read the actual code to find the right variable names.
- The `BulkJob` constructor may not accept `max_files` yet. **Add a `max_files: Optional[int] = None` parameter** to `BulkJob.__init__()` in `core/bulk_worker.py`. When set, the job stops after converting that many files. Implement this as a counter check in the worker loop — after `max_files` files complete, set the job status to `completed` and stop workers.
- The `bulk_jobs` INSERT may not match the existing column set exactly. Check `_ensure_schema()` for the actual `bulk_jobs` columns and match them. The key addition is `auto_triggered`.
- For **immediate** mode, `await job.run()` blocks. Since lifecycle scans use `max_instances=1` in APScheduler, this is safe.
- For **queued** and **scheduled** modes (when the scheduled window is open), `asyncio.create_task()` fires the job and the scanner continues.

### 6.2 Modify `core/scheduler.py`

Add the hourly aggregation job and deferred conversion runner.

**In `start_scheduler()`**, add these jobs alongside the existing ones:

```python
from core.auto_metrics_aggregator import aggregate_hourly_metrics

scheduler.add_job(
    _wrap_async(aggregate_hourly_metrics),  # Use whatever async wrapper pattern exists
    "cron",
    minute=5,  # Run at :05 past every hour
    id="auto_metrics_aggregation",
    max_instances=1,
    replace_existing=True,
)

scheduler.add_job(
    _wrap_async(_run_deferred_conversions),
    "interval",
    minutes=15,
    id="deferred_conversion_runner",
    max_instances=1,
    replace_existing=True,
)
```

**In the daily maintenance function** (the one that runs at 03:00), add:

```python
from core.auto_metrics_aggregator import purge_old_auto_metrics
await purge_old_auto_metrics()
```

**Add the deferred conversion runner function:**

```python
async def _run_deferred_conversions():
    """Check for deferred auto-conversion jobs and start them if in-window.

    Only relevant in 'scheduled' mode. Checks if we're now inside a
    conversion window and picks up any pending deferred runs.
    """
    from core.auto_converter import get_auto_conversion_engine
    from core.database import get_preference

    mode = await get_preference("auto_convert_mode") or "off"
    if mode != "scheduled":
        return

    engine = get_auto_conversion_engine()
    hist = await engine._get_historical_context()

    if not await engine._is_in_conversion_window(hist):
        return

    # Find pending deferred runs
    import aiosqlite
    from core.database import get_db_path

    try:
        async with aiosqlite.connect(get_db_path()) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await conn.execute_fetchall(
                """
                SELECT id, scan_run_id, workers_chosen, batch_size_chosen
                FROM auto_conversion_runs
                WHERE status = 'deferred' AND mode = 'scheduled'
                ORDER BY started_at ASC
                LIMIT 1
                """,
            )

            if not rows:
                return

            run = rows[0]

            # Update status to running
            await conn.execute(
                "UPDATE auto_conversion_runs SET status = 'running' WHERE id = ?",
                (run["id"],),
            )
            await conn.commit()

        logger.info(
            "deferred_conversion_starting",
            event="deferred_conversion_starting",
            run_id=run["id"],
            scan_run_id=run["scan_run_id"],
            workers=run["workers_chosen"],
            batch_size=run["batch_size_chosen"],
        )

        # Trigger the conversion through the lifecycle scanner's execute method
        # or directly create a BulkJob here
        # (Implementation depends on how scanner exposes source/output paths)

    except Exception as e:
        logger.error("deferred_conversion_failed", error=str(e))
```

**Note:** The async wrapping pattern depends on how existing scheduler jobs handle async functions. Check how `lifecycle_scan` is scheduled — it likely uses a wrapper like `_wrap_async()` or `asyncio.run()` in a thread. Use the same pattern.

### 6.3 Modify `core/bulk_worker.py`

Add `max_files` support to `BulkJob`:

1. Add `max_files: Optional[int] = None` parameter to `BulkJob.__init__()`
2. Store it as `self._max_files`
3. In the worker loop (wherever files are dequeued and processed), add a counter check:

```python
# In the worker loop, after a file is successfully processed:
self._files_completed += 1
if self._max_files and self._files_completed >= self._max_files:
    logger.info(
        "auto_convert_batch_limit_reached",
        event="auto_convert_batch_limit_reached",
        job_id=self.job_id,
        max_files=self._max_files,
        completed=self._files_completed,
    )
    break  # or signal workers to stop
```

Also add `auto_triggered: bool = False` to the constructor if creating jobs needs to pass this flag.

---

## 7. API Endpoints

### 7.1 New File: `api/routes/auto_convert.py`

```python
"""Auto-conversion engine API endpoints."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_role, UserRole
from core.auto_converter import get_auto_conversion_engine

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auto-convert", tags=["auto-convert"])


@router.get("/status", dependencies=[Depends(require_role(UserRole.OPERATOR))])
async def get_auto_convert_status():
    """Return current auto-conversion engine status."""
    engine = get_auto_conversion_engine()
    return engine.get_status()


@router.post("/override", dependencies=[Depends(require_role(UserRole.MANAGER))])
async def set_mode_override(
    mode: str = Query(..., regex="^(off|immediate|queued|scheduled)$"),
    duration_minutes: int = Query(60, ge=5, le=1440),
):
    """Set a temporary mode override.

    Lasts for duration_minutes then reverts to Settings value.
    Does not persist across container restarts.
    """
    engine = get_auto_conversion_engine()
    try:
        engine.set_mode_override(mode, duration_minutes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": "ok",
        "mode": mode,
        "expires_in_minutes": duration_minutes,
    }


@router.post("/clear-override", dependencies=[Depends(require_role(UserRole.MANAGER))])
async def clear_mode_override():
    """Clear any active mode override."""
    engine = get_auto_conversion_engine()
    engine.clear_mode_override()
    return {"status": "ok"}


@router.get("/history", dependencies=[Depends(require_role(UserRole.MANAGER))])
async def get_auto_convert_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Return recent auto-conversion decisions."""
    import aiosqlite
    from core.database import get_db_path

    async with aiosqlite.connect(get_db_path()) as conn:
        conn.row_factory = aiosqlite.Row

        rows = await conn.execute_fetchall(
            """
            SELECT * FROM auto_conversion_runs
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

        count_row = await conn.execute_fetchall(
            "SELECT COUNT(*) as total FROM auto_conversion_runs"
        )
        total = count_row[0]["total"] if count_row else 0

    return {
        "runs": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/metrics-summary", dependencies=[Depends(require_role(UserRole.MANAGER))])
async def get_auto_metrics_summary():
    """Return a summary of collected auto_metrics data.

    Shows patterns by day-of-week and hour for the engine's learning.
    Useful for understanding what the engine "knows" about system patterns.
    """
    import aiosqlite
    from core.database import get_db_path

    async with aiosqlite.connect(get_db_path()) as conn:
        conn.row_factory = aiosqlite.Row

        # Heatmap data: average CPU by hour and day
        rows = await conn.execute_fetchall(
            """
            SELECT
                day_of_week,
                cast(strftime('%H', hour_bucket) as integer) as hour,
                AVG(cpu_avg) as cpu,
                AVG(memory_avg) as memory,
                AVG(user_request_count) as requests,
                COUNT(*) as samples
            FROM auto_metrics
            GROUP BY day_of_week, hour
            ORDER BY day_of_week, hour
            """
        )

        total_row = await conn.execute_fetchall(
            "SELECT COUNT(*) as total FROM auto_metrics"
        )
        total_samples = total_row[0]["total"] if total_row else 0

    return {
        "heatmap": [dict(r) for r in rows],
        "total_hourly_buckets": total_samples,
    }
```

### 7.2 Register Router in `main.py`

In the router registration section of `main.py`, add:

```python
from api.routes.auto_convert import router as auto_convert_router
app.include_router(auto_convert_router)
```

---

## 8. Database Schema Changes

### 8.1 Add Tables in `core/database.py`

In `_ensure_schema()`, after existing table creation, add:

```python
# ── Auto-conversion tables (v0.11.0) ──
await conn.execute("""
    CREATE TABLE IF NOT EXISTS auto_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hour_bucket TEXT NOT NULL,
        day_of_week INTEGER NOT NULL,
        cpu_avg REAL NOT NULL,
        cpu_p95 REAL NOT NULL,
        memory_avg REAL NOT NULL,
        memory_peak REAL NOT NULL,
        active_conversions_avg REAL NOT NULL DEFAULT 0,
        files_converted INTEGER NOT NULL DEFAULT 0,
        conversion_throughput REAL NOT NULL DEFAULT 0,
        io_read_rate_avg REAL NOT NULL DEFAULT 0,
        io_write_rate_avg REAL NOT NULL DEFAULT 0,
        user_request_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")
await conn.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_metrics_bucket
    ON auto_metrics(hour_bucket)
""")
await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_auto_metrics_dow_hour
    ON auto_metrics(day_of_week, cast(strftime('%H', hour_bucket) as integer))
""")

await conn.execute("""
    CREATE TABLE IF NOT EXISTS auto_conversion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_run_id TEXT,
        mode TEXT NOT NULL,
        was_override INTEGER NOT NULL DEFAULT 0,
        files_discovered INTEGER NOT NULL DEFAULT 0,
        files_queued INTEGER NOT NULL DEFAULT 0,
        batch_size_chosen INTEGER NOT NULL DEFAULT 0,
        workers_chosen INTEGER NOT NULL DEFAULT 0,
        cpu_at_decision REAL,
        memory_at_decision REAL,
        cpu_hist_avg REAL,
        reason TEXT,
        bulk_job_id TEXT,
        started_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
    )
""")
await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_auto_runs_status
    ON auto_conversion_runs(status)
""")
await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_auto_runs_started
    ON auto_conversion_runs(started_at)
""")

# Add auto_triggered column to bulk_jobs (idempotent)
try:
    await conn.execute(
        "ALTER TABLE bulk_jobs ADD COLUMN auto_triggered INTEGER DEFAULT 0"
    )
except Exception:
    pass  # Column already exists
```

---

## 9. Settings UI: Auto-Conversion Section

### 9.1 Add Section to `static/settings.html`

Add a new section heading. Place it after the "Bulk Conversion" section and before "Password Recovery":

```html
<!-- Auto-Conversion section -->
<h3 data-help="settings-guide#auto-conversion">Auto-Conversion</h3>
<p class="section-help">
    Automatically convert new and modified files found by the lifecycle scanner.
    The engine adapts its behavior based on system load and historical usage patterns
    to avoid impacting the system during busy periods.
    <a href="/help#auto-conversion">Learn more →</a>
</p>
```

The preference controls for this section are rendered dynamically by the existing settings JS from `_PREFERENCE_SCHEMA` (since all keys have `"section": "auto_conversion"`). Verify the settings page JS uses the `section` field to group preferences into sections.

### 9.2 Schedule Windows Editor

The `auto_convert_schedule_windows` preference is a JSON string. The default text input is poor UX for this. Add a custom renderer in the settings JS for this specific key:

```javascript
// In the settings page JS, when rendering preference controls,
// add a check for the schedule_windows key:
if (key === 'auto_convert_schedule_windows') {
    renderScheduleWindowsEditor(container, value, key);
    return;
}

function renderScheduleWindowsEditor(container, value, key) {
    let windows = [];
    try { windows = JSON.parse(value || '[]'); } catch { windows = []; }

    const wrapper = document.createElement('div');
    wrapper.className = 'schedule-windows-editor';

    function render() {
        wrapper.innerHTML = '';

        if (windows.length === 0) {
            const note = document.createElement('p');
            note.className = 'setting-description';
            note.textContent = 'No windows configured — MarkFlow will auto-detect quiet periods from historical data.';
            wrapper.appendChild(note);
        }

        windows.forEach((w, i) => {
            const row = document.createElement('div');
            row.className = 'schedule-window-row';
            row.innerHTML = `
                <select class="sw-start" data-idx="${i}">
                    ${hourOptions(w.start || '00:00')}
                </select>
                <span>to</span>
                <select class="sw-end" data-idx="${i}">
                    ${hourOptions(w.end || '05:00')}
                </select>
                ${dayCheckboxes(w.days || [0,1,2,3,4,5,6], i)}
                <button class="btn-icon sw-remove" data-idx="${i}" title="Remove">×</button>
            `;
            wrapper.appendChild(row);
        });

        const addBtn = document.createElement('button');
        addBtn.className = 'btn btn-sm';
        addBtn.textContent = '+ Add Window';
        addBtn.addEventListener('click', () => {
            windows.push({ start: '00:00', end: '05:00', days: [0,1,2,3,4] });
            render();
            save();
        });
        wrapper.appendChild(addBtn);

        // Bind change events
        wrapper.querySelectorAll('.sw-start, .sw-end').forEach(sel => {
            sel.addEventListener('change', () => {
                const idx = parseInt(sel.dataset.idx);
                if (sel.classList.contains('sw-start')) windows[idx].start = sel.value;
                else windows[idx].end = sel.value;
                save();
            });
        });

        wrapper.querySelectorAll('.sw-day').forEach(cb => {
            cb.addEventListener('change', () => {
                const idx = parseInt(cb.dataset.idx);
                const day = parseInt(cb.dataset.day);
                if (cb.checked) {
                    if (!windows[idx].days.includes(day)) windows[idx].days.push(day);
                } else {
                    windows[idx].days = windows[idx].days.filter(d => d !== day);
                }
                windows[idx].days.sort();
                save();
            });
        });

        wrapper.querySelectorAll('.sw-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                windows.splice(parseInt(btn.dataset.idx), 1);
                render();
                save();
            });
        });
    }

    function save() {
        const json = windows.length > 0 ? JSON.stringify(windows) : '';
        // Call the existing preference save function
        savePref(key, json);
    }

    function hourOptions(selected) {
        let html = '';
        for (let h = 0; h < 24; h++) {
            const val = `${String(h).padStart(2, '0')}:00`;
            html += `<option value="${val}" ${val === selected ? 'selected' : ''}>${val}</option>`;
        }
        return html;
    }

    function dayCheckboxes(days, idx) {
        const names = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
        return names.map((n, d) =>
            `<label class="sw-day-label">
                <input type="checkbox" class="sw-day" data-idx="${idx}" data-day="${d}"
                    ${days.includes(d) ? 'checked' : ''}>
                ${n}
            </label>`
        ).join('');
    }

    render();
    container.appendChild(wrapper);
}
```

### 9.3 CSS for Schedule Windows Editor

Add to `markflow.css`:

```css
/* Schedule windows editor */
.schedule-windows-editor {
    margin: 0.5rem 0;
}

.schedule-window-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
}

.schedule-window-row select {
    padding: 0.3rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    color: var(--text);
    font-size: 0.85rem;
}

.sw-day-label {
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    font-size: 0.8rem;
    cursor: pointer;
}

.sw-day-label input[type="checkbox"] {
    margin: 0;
}

.sw-remove {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 1.2rem;
    cursor: pointer;
    padding: 0.15rem 0.35rem;
    border-radius: var(--radius);
}

.sw-remove:hover {
    color: var(--danger, #ef4444);
    background: var(--danger-bg, #fef2f2);
}
```

---

## 10. Status Page: Auto-Conversion Card

### 10.1 Add Card to `static/status.html`

Add an "Auto-Conversion" card at the top of the status page, before the per-job cards:

```html
<!-- Auto-Conversion Engine Card -->
<div class="job-card auto-convert-card" id="auto-convert-card">
    <div class="card-header">
        <h3 data-help="auto-conversion">Auto-Conversion Engine</h3>
    </div>
    <div class="card-body">
        <div class="auto-convert-controls">
            <label>Mode:
                <select id="ac-mode-select" class="mode-select">
                    <option value="off">Off</option>
                    <option value="immediate">Immediate</option>
                    <option value="queued">Queued</option>
                    <option value="scheduled">Scheduled</option>
                </select>
            </label>
            <span id="ac-override-badge" class="override-badge" style="display:none">
                Override active (<span id="ac-override-time"></span> left)
            </span>
            <button id="ac-clear-override" class="btn btn-sm" style="display:none">Clear Override</button>
        </div>
        <div id="ac-last-decision" class="last-decision" style="display:none"></div>
        <div class="card-actions">
            <a href="#" id="ac-history-link" class="btn btn-sm btn-outline">View Decision History</a>
        </div>
    </div>
</div>
```

### 10.2 JavaScript for Status Page Auto-Conversion Card

Add to the status page's `<script>` section (or a separate included file):

```javascript
// ── Auto-Conversion Card Logic ──

let acCurrentMode = 'off';
let acOverrideActive = false;

async function loadAutoConvertStatus() {
    try {
        const resp = await fetch('/api/auto-convert/status');
        if (!resp.ok) return;
        const data = await resp.json();

        // Update mode dropdown
        const select = document.getElementById('ac-mode-select');
        if (data.override_active && data.mode_override) {
            select.value = data.mode_override;
            acOverrideActive = true;
        } else {
            // Load from preferences
            const prefsResp = await fetch('/api/preferences');
            if (prefsResp.ok) {
                const prefs = await prefsResp.json();
                const mode = (prefs.preferences || prefs)['auto_convert_mode'] || 'off';
                select.value = mode;
            }
            acOverrideActive = false;
        }

        // Override badge
        const badge = document.getElementById('ac-override-badge');
        const clearBtn = document.getElementById('ac-clear-override');
        if (data.override_active) {
            const expiry = new Date(data.override_expiry);
            const now = new Date();
            const minsLeft = Math.max(0, Math.round((expiry - now) / 60000));
            document.getElementById('ac-override-time').textContent = `${minsLeft} min`;
            badge.style.display = 'inline-block';
            clearBtn.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
            clearBtn.style.display = 'none';
        }

        // Last decision
        const decisionEl = document.getElementById('ac-last-decision');
        if (data.last_decision) {
            decisionEl.textContent = data.last_decision.reason || 'No details';
            decisionEl.style.display = 'block';
        }
    } catch (err) {
        console.error('Failed to load auto-convert status:', err);
    }
}

// Mode change → set override
document.getElementById('ac-mode-select').addEventListener('change', async (e) => {
    const mode = e.target.value;
    try {
        const resp = await fetch(`/api/auto-convert/override?mode=${mode}&duration_minutes=60`, {
            method: 'POST',
        });
        if (resp.ok) {
            showToast(`Auto-conversion mode overridden to "${mode}" for 60 minutes`);
            loadAutoConvertStatus();
        }
    } catch (err) {
        showToast('Failed to set override', 'error');
    }
});

// Clear override
document.getElementById('ac-clear-override').addEventListener('click', async () => {
    try {
        await fetch('/api/auto-convert/clear-override', { method: 'POST' });
        showToast('Override cleared');
        loadAutoConvertStatus();
    } catch (err) {
        showToast('Failed to clear override', 'error');
    }
});

// Poll every 30 seconds
loadAutoConvertStatus();
setInterval(loadAutoConvertStatus, 30000);
```

### 10.3 CSS for Auto-Conversion Card

Add to `markflow.css`:

```css
.auto-convert-card {
    border-left: 3px solid var(--info, #3b82f6);
}

.auto-convert-controls {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
}

.mode-select {
    padding: 0.35rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    color: var(--text);
    font-size: 0.9rem;
}

.override-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    background: var(--warning-bg, #fffbeb);
    color: var(--warning, #f59e0b);
    font-size: 0.75rem;
    font-weight: 600;
}

.last-decision {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin-top: 0.5rem;
    font-family: var(--font-mono, monospace);
    padding: 0.5rem;
    background: var(--surface);
    border-radius: var(--radius);
    white-space: pre-wrap;
    word-break: break-word;
}
```

---

## 11. Schedule Window Validation

Add a validation function in `core/database.py` (near the other preference validators):

```python
def _validate_schedule_windows(value: str) -> tuple[bool, str]:
    """Validate the schedule windows JSON string."""
    if not value or not value.strip():
        return True, ""  # Empty is valid (means auto-detect)

    try:
        windows = json.loads(value)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    if not isinstance(windows, list):
        return False, "Must be a JSON array"

    for i, w in enumerate(windows):
        if not isinstance(w, dict):
            return False, f"Window {i+1} must be an object"
        if "start" not in w or "end" not in w:
            return False, f"Window {i+1} must have 'start' and 'end'"

        for fld in ("start", "end"):
            try:
                h, m = map(int, w[fld].split(":"))
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                return False, f"Window {i+1} '{fld}' must be HH:MM format"

        if "days" in w:
            if not isinstance(w["days"], list):
                return False, f"Window {i+1} 'days' must be an array"
            for d in w["days"]:
                if not isinstance(d, int) or not (0 <= d <= 6):
                    return False, f"Window {i+1} days must be integers 0-6 (Mon=0, Sun=6)"

    return True, ""
```

Wire this into the preference validation system. The `_PREFERENCE_SCHEMA` entry for `auto_convert_schedule_windows` has `"validate": "_validate_schedule_windows"`. Ensure the `PUT /api/preferences/{key}` endpoint calls this function when the key matches. Check how existing validate functions are dispatched — if there's a dispatch dict, add this entry. If validation is by convention (function name lookup), ensure the function is importable.

---

## 12. Help Wiki Updates

### 12.1 New Help Article: `docs/help/auto-conversion.md`

Create this article (150-300 lines) covering:
- What auto-conversion is and why it exists
- The three modes explained in plain language (immediate, queued, scheduled)
- How dynamic scaling works ("MarkFlow watches how busy the system is...")
- Business hours concept
- The status page override and when you'd use it
- Schedule windows (explicit and auto-detect)
- The conservatism factor slider
- When to use which mode (practical advice)

Write for the same non-technical audience as the other help articles.

### 12.2 Update `docs/help/_index.json`

Add the new article under "Core Features" after "Bulk Repository Conversion":

```json
{
    "slug": "auto-conversion",
    "title": "Auto-Conversion",
    "description": "Automatic conversion of new and modified files"
}
```

### 12.3 Update `docs/help/settings-guide.md`

Add a section for "Auto-Conversion" settings documenting each of the 9 new preferences.

### 12.4 Update `docs/help/status-page.md`

Add a section about the auto-conversion card on the status page, including the mode override feature.

---

## 13. Files to Create

| File | Purpose |
|------|---------|
| `core/auto_converter.py` | Auto-conversion decision engine — mode selection, worker scaling, batch sizing, historical learning |
| `core/auto_metrics_aggregator.py` | Hourly aggregation of raw metrics into `auto_metrics` table + retention purge |
| `api/routes/auto_convert.py` | Auto-conversion API: status, override, history, metrics summary |
| `docs/help/auto-conversion.md` | Help article for auto-conversion feature |

---

## 14. Files to Modify

| File | Change |
|------|--------|
| `core/database.py` | Add `auto_metrics` + `auto_conversion_runs` tables to `_ensure_schema()`. Add 9 new preference keys to `_PREFERENCE_SCHEMA`. Add `auto_triggered` column to `bulk_jobs`. Add `_validate_schedule_windows()`. Add auto-conversion keys to `_SYSTEM_PREF_KEYS`. |
| `core/lifecycle_scanner.py` | Call `engine.on_scan_complete()` after scan. Add `_execute_auto_conversion()` method. |
| `core/scheduler.py` | Add hourly aggregation job. Add `purge_old_auto_metrics()` to daily maintenance. Add `_run_deferred_conversions()` for scheduled mode. |
| `core/bulk_worker.py` | Add `max_files` parameter to `BulkJob`. Add `auto_triggered` flag. Implement batch limit check in worker loop. |
| `main.py` | Register `auto_convert_router`. |
| `static/settings.html` | Add Auto-Conversion section heading with `data-help` and `section-help`. Add `renderScheduleWindowsEditor()` JS function. |
| `static/status.html` | Add auto-conversion card with mode override, last decision, history link. Add polling JS. |
| `static/markflow.css` | Add `.auto-convert-card`, `.mode-select`, `.override-badge`, `.last-decision`, `.schedule-windows-editor` styles. |
| `docs/help/_index.json` | Add auto-conversion article entry. |
| `docs/help/settings-guide.md` | Add auto-conversion settings section. |
| `docs/help/status-page.md` | Add auto-conversion card section. |
| `CLAUDE.md` | Add v0.11.0 entry + gotchas. |

---

## 15. Test Requirements

### New Tests: `tests/test_auto_converter.py`

| Test | What It Verifies |
|------|-----------------|
| `test_decision_off_mode` | Engine returns `should_convert=False` when mode is `off` |
| `test_decision_no_files` | Engine returns `should_convert=False` when 0 files discovered |
| `test_decision_immediate_mode` | Engine returns `should_convert=True` with mode `immediate` |
| `test_decision_queued_mode` | Engine returns `should_convert=True` with mode `queued` |
| `test_decision_scheduled_in_window` | Returns `should_convert=True` when inside configured window |
| `test_decision_scheduled_outside_window` | Returns `should_convert=False` with `deferred_until` set |
| `test_worker_auto_scaling` | Auto workers scale down under high CPU load |
| `test_worker_fixed_value` | Fixed worker pref returns exact number |
| `test_batch_size_business_hours` | Batch size is smaller during business hours than off hours |
| `test_batch_size_dead_hours` | Batch size is larger during dead hours (00:00-05:00) |
| `test_batch_size_fixed_value` | Fixed batch size pref returns exact number |
| `test_mode_override_set` | `set_mode_override()` changes effective mode |
| `test_mode_override_expiry` | Override expires after duration and reverts to pref |
| `test_mode_override_clear` | `clear_mode_override()` resets to pref |
| `test_conservative_factor` | Lower conservatism factor = fewer workers and smaller batches |
| `test_historical_context_used` | With populated `auto_metrics`, decisions factor in historical CPU avg |
| `test_no_history_fallback` | Without history, decisions still produce valid results |
| `test_decision_logged_to_db` | `auto_conversion_runs` gets a row after each decision |
| `test_decision_logging_levels` | Normal/Elevated/Developer produce different log detail |
| `test_schedule_windows_validation_valid` | Valid JSON passes validation |
| `test_schedule_windows_validation_invalid` | Invalid JSON fails validation |
| `test_schedule_windows_empty_valid` | Empty string passes (auto-detect mode) |

### New Tests: `tests/test_auto_metrics_aggregator.py`

| Test | What It Verifies |
|------|-----------------|
| `test_hourly_aggregation` | Raw samples are aggregated into single `auto_metrics` row |
| `test_aggregation_idempotent` | Running twice for same hour doesn't duplicate |
| `test_aggregation_no_samples` | No samples for an hour = no `auto_metrics` row created |
| `test_purge_old_metrics` | Rows older than retention days are deleted |
| `test_purge_respects_retention_pref` | Changing `auto_metrics_retention_days` changes purge cutoff |

### New Tests: `tests/test_auto_convert_api.py`

| Test | What It Verifies |
|------|-----------------|
| `test_get_status` | `GET /api/auto-convert/status` returns engine state |
| `test_set_override_requires_manager` | Override endpoint rejects operator role |
| `test_set_override_valid` | Override with valid mode returns success |
| `test_set_override_invalid_mode` | Invalid mode returns 400 or 422 |
| `test_clear_override` | Clear override returns success |
| `test_history_endpoint` | History returns list of past runs with pagination |
| `test_metrics_summary` | Metrics summary returns heatmap data structure |

---

## 16. Grafana Integration Notes

All auto-conversion decision logs are structured for Grafana/Loki/Promtail ingestion. No additional Grafana configuration is needed beyond pointing Promtail at the `logs/markflow.log` file.

### 16.1 Queryable Log Fields

| Field | Type | Description | Example Loki Query |
|-------|------|-------------|--------------------|
| `event` | string | Always `auto_convert_decision` | `{app="markflow"} \| json \| event="auto_convert_decision"` |
| `mode` | string | `immediate`, `queued`, `scheduled`, `off` | `\| mode="immediate"` |
| `should_convert` | bool | Whether conversion was triggered | `\| should_convert=true` |
| `workers` | int | Workers chosen | `\| workers > 4` |
| `batch_size` | int | Files per batch | `\| batch_size > 100` |
| `hour` | int | Hour of day (0-23) | `\| hour >= 6 \| hour < 18` |
| `day_name` | string | Mon, Tue, etc. | `\| day_name="Mon"` |
| `period` | string | `business` or `off_hours` | `\| period="business"` |
| `reason` | string | Full reasoning string | `\| reason=~".*conservative.*"` |
| `scan_run_id` | string | Links to the triggering scan | Correlation queries |
| `files_discovered` | int | Total new + modified files | `\| files_discovered > 50` |

### 16.2 Example Grafana Dashboard Panels

- **Decisions Over Time** — time-series of `should_convert` true vs false events
- **Worker Count Distribution** — bar chart of `workers` values over time
- **Business vs Off-Hours** — pie chart of `period` values
- **Batch Size Trends** — line chart of `batch_size` over time
- **CPU at Decision Time** — overlay of CPU from `metrics_snapshot` on decision events

### 16.3 Additional Grafana-Ready Events

| Event Name | When Emitted | Key Fields |
|------------|-------------|------------|
| `auto_convert_mode_override_set` | Status page override activated | `mode`, `duration_minutes`, `expires_at` |
| `auto_convert_mode_override_cleared` | Override cleared | `previous_mode` |
| `auto_convert_job_created` | BulkJob created by engine | `job_id`, `mode`, `workers`, `batch_size`, `scan_run_id` |
| `auto_convert_job_deferred` | Scheduled job deferred | `job_id`, `deferred_until` |
| `auto_convert_batch_limit_reached` | max_files cap hit | `job_id`, `max_files`, `completed` |
| `auto_convert_execution_failed` | Error creating/starting job | `error`, `scan_run_id` |
| `auto_metrics_aggregated` | Hourly rollup completed | `hour_bucket`, `cpu_avg`, `cpu_p95`, `memory_avg`, `samples` |
| `auto_metrics_purged` | Old metrics deleted | `metrics_deleted`, `runs_deleted`, `retention_days` |
| `deferred_conversion_starting` | Scheduled job starting | `run_id`, `scan_run_id`, `workers`, `batch_size` |

---

## 17. CLAUDE.md Updates

### Version Entry

```
**v0.11.0** — Intelligent auto-conversion engine. Three modes: immediate
  (converts within scan cycle), queued (background task after scan),
  scheduled (time-window or auto-detected quiet periods). Dynamic worker
  scaling based on real-time CPU/memory + historical averages per hour/day.
  Intelligent batch sizing adapts to time of day, system load, and
  historical access patterns. Business hours awareness (default 6a-6p
  weekdays) with configurable conservatism factor. Historical metrics
  stored in `auto_metrics` table (hourly aggregation from raw samples)
  + structured JSON logs for Grafana/Loki. Decision reasoning logged at
  selectable verbosity (Normal/Elevated/Developer) with Grafana-queryable
  field names. Status page gains auto-conversion card with ephemeral mode
  override (dropdown + timer). 9 new preferences in `auto_conversion`
  section (all Manager-gated). Schedule windows editor in Settings with
  JSON validation. `auto_conversion_runs` table tracks all decisions for
  audit. New `core/auto_converter.py` (decision engine singleton),
  `core/auto_metrics_aggregator.py` (hourly rollup + retention purge),
  `api/routes/auto_convert.py` (status, override, history, metrics
  summary). `bulk_jobs` gains `auto_triggered` column. APScheduler gains
  hourly aggregation job + deferred conversion runner. 33 new tests.
```

### New Gotchas

```
- **Auto-conversion mode override is in-memory only**: The status page
  override does not persist to the database or survive container restarts.
  This is intentional — prevents a forgotten override from silently
  changing behavior weeks later.

- **auto_metrics vs system_metrics**: Two separate tables with different
  purposes. `system_metrics` has 30-second raw samples for the Resources
  page charts. `auto_metrics` has hourly aggregates used by the decision
  engine for pattern learning. They share a data source (psutil) but serve
  different consumers. Do not merge them.

- **Hourly aggregation runs at :05, not :00**: The 5-minute offset ensures
  the last samples from the previous hour are written before aggregation.
  If the collector is behind (unlikely), a few samples may fall into the
  next hour's bucket — acceptable for aggregate accuracy.

- **Conservative factor stacks during business hours**: The base factor
  (default 0.7) is multiplied by an additional 0.7 during business hours,
  giving an effective factor of ~0.49. This is intentional — business
  hours should be noticeably throttled.

- **Dead hours fallback is hardcoded 00:00-05:00**: Even with no historical
  data, midnight-to-5am is treated as a safe conversion window for
  scheduled auto-detect mode. This is the fallback when `auto_metrics`
  has insufficient data to determine quiet periods.

- **Immediate mode blocks the scanner**: In immediate mode, the scanner
  waits for the conversion batch to complete before the scan cycle ends.
  Since lifecycle scans use `max_instances=1` in APScheduler, this is
  safe — the next scan simply starts later. If a conversion takes longer
  than the scan interval, the next scan queues behind it.

- **create_bulk_job needs auto_triggered parameter**: The existing function
  or INSERT statement must accept `auto_triggered=True` and store it on
  the job record. This lets the UI distinguish manual from automatic jobs.
  Add the parameter with default `False` to avoid breaking existing callers.

- **Schedule windows JSON format**: Array of objects with `start` (HH:MM),
  `end` (HH:MM), and optional `days` (array of 0-6, Monday=0). Empty
  string means auto-detect from historical data. Invalid JSON is
  rejected by `_validate_schedule_windows()` before saving.

- **Decision logging field names are a stable interface**: The Grafana
  dashboard queries these field names. Do not rename `event`, `mode`,
  `workers`, `batch_size`, `hour`, `day_name`, `period`, or `reason`
  without updating the Grafana dashboard configuration.

- **Engine singleton is per-process**: `get_auto_conversion_engine()`
  returns a module-level singleton. The MCP server (separate process)
  does NOT have its own engine instance — auto-conversion only runs
  in the main MarkFlow process.

- **purge_old_auto_metrics runs in daily maintenance**: Added to the
  03:00 maintenance job alongside existing `purge_old_metrics()`. Uses
  `auto_metrics_retention_days` preference (default 30, min 7, max 365).
  Also purges `auto_conversion_runs` older than retention.

- **BulkJob max_files is a soft cap**: The job checks the counter after
  each file completes. If `max_files=50` and 4 workers are running, up
  to 53 files might be processed (50 + 3 in-flight when the cap is hit).
  This is acceptable — exact cap enforcement would require canceling
  in-progress conversions.
```

---

## 18. Done Criteria Checklist

- [ ] `core/auto_converter.py` exists with `AutoConversionEngine` class
- [ ] `AutoConvertDecision` dataclass returned by all decisions
- [ ] Three modes work: immediate, queued, scheduled
- [ ] "Off" mode returns `should_convert=False`
- [ ] Zero discovered files returns `should_convert=False`
- [ ] Worker auto-scaling uses current CPU + historical avg + conservative factor
- [ ] Fixed worker preference returns exact count
- [ ] Batch auto-sizing adapts to business hours / dead hours / off hours
- [ ] Fixed batch preference caps correctly
- [ ] Business hours configurable via preferences (default 6a-6p weekdays)
- [ ] Conservative factor configurable (default 0.7)
- [ ] Business hours stack additional 0.7 multiplier on conservative factor
- [ ] `core/auto_metrics_aggregator.py` exists with `aggregate_hourly_metrics()` and `purge_old_auto_metrics()`
- [ ] Hourly aggregation runs via APScheduler at :05
- [ ] `auto_metrics` table created in `_ensure_schema()`
- [ ] `auto_conversion_runs` table created in `_ensure_schema()`
- [ ] `bulk_jobs.auto_triggered` column added (idempotent ALTER)
- [ ] Aggregation is idempotent (won't duplicate on re-run)
- [ ] Retention purge deletes old `auto_metrics` and `auto_conversion_runs`
- [ ] Retention configurable via preference (default 30 days)
- [ ] `api/routes/auto_convert.py` exists with status, override, clear-override, history, metrics-summary endpoints
- [ ] Status endpoint returns engine state (override info + last decision)
- [ ] Override endpoint requires Manager role
- [ ] Override expires after configured duration
- [ ] Clear-override endpoint works
- [ ] History endpoint returns past decisions with pagination
- [ ] Metrics summary returns heatmap data by day+hour
- [ ] Router registered in `main.py`
- [ ] Lifecycle scanner calls engine after scan completion
- [ ] Immediate mode creates + runs BulkJob in scan cycle (blocking)
- [ ] Queued mode creates + runs BulkJob via `asyncio.create_task()` (non-blocking)
- [ ] Scheduled mode defers job until window opens
- [ ] Deferred conversion runner picks up pending scheduled jobs every 15 min
- [ ] `BulkJob` accepts `max_files` parameter and stops after that many files
- [ ] Schedule windows validation works (valid JSON, HH:MM format, day range 0-6)
- [ ] Empty schedule windows enables auto-detect mode
- [ ] 9 new preferences added to `_PREFERENCE_SCHEMA` with `section: "auto_conversion"`
- [ ] All auto-conversion prefs added to `_SYSTEM_PREF_KEYS` (Manager-gated)
- [ ] Settings page shows Auto-Conversion section with `data-help` and `section-help`
- [ ] Schedule windows editor renders in settings (add/remove windows, day checkboxes)
- [ ] Status page shows auto-conversion card
- [ ] Mode override dropdown on status page works
- [ ] Override countdown timer visible when active
- [ ] Last decision summary shown on status card
- [ ] Decision history link works
- [ ] Decision logs use consistent Grafana-queryable field names
- [ ] Decision log level selectable in settings (Normal/Elevated/Developer)
- [ ] Normal level logs action only (mode, should_convert, workers, batch_size)
- [ ] Elevated level adds full reasoning, time context, files_discovered
- [ ] Developer level adds raw metrics_snapshot
- [ ] Help article created: `docs/help/auto-conversion.md`
- [ ] `docs/help/_index.json` updated with new article
- [ ] `docs/help/settings-guide.md` updated with auto-conversion section
- [ ] `docs/help/status-page.md` updated with auto-conversion card section
- [ ] All 33 tests pass
- [ ] `CLAUDE.md` updated with v0.11.0 entry + all gotchas
