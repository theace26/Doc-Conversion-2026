"""Tests for v0.12.1 bugfix + stability patch.

Validates fixes for:
- Bug 2: structlog double event argument
- Bug 3: SQLite WAL mode + busy_timeout on all connections
- Bug 4: collect_metrics interval and timeout
- Bug 5: DB compaction no longer deferred by scan_running guard
- Bug 6: MCP connection uses Docker service name
- Fix 8: Startup orphan job recovery
- Fix 9: Stop banner CSS specificity
- Fix 10: Progress tracker (already existed, validated here)
"""
import ast
import time

import pytest


class TestStructlogEventArg:
    """Bug 2: structlog calls should not pass event as both positional and keyword."""

    def test_lifecycle_scanner_no_double_event(self):
        """Verify lifecycle_scanner.py has no double-event structlog calls."""
        with open("core/lifecycle_scanner.py", "r") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "error", "info", "warning", "debug"
                ):
                    has_positional = len(node.args) > 0
                    has_event_kwarg = any(kw.arg == "event" for kw in node.keywords)
                    assert not (has_positional and has_event_kwarg), (
                        f"Line {node.lineno}: structlog call has both positional "
                        f"and event= keyword argument"
                    )

    def test_auto_metrics_aggregator_no_double_event(self):
        """Verify auto_metrics_aggregator.py has no double-event structlog calls."""
        with open("core/auto_metrics_aggregator.py", "r") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "error", "info", "warning", "debug"
                ):
                    has_positional = len(node.args) > 0
                    has_event_kwarg = any(kw.arg == "event" for kw in node.keywords)
                    assert not (has_positional and has_event_kwarg), (
                        f"Line {node.lineno}: structlog call has both positional "
                        f"and event= keyword argument"
                    )


class TestSQLiteWALMode:
    """Bug 3: Database should use WAL mode for concurrent access."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self):
        """Verify WAL mode is active on the database."""
        import aiosqlite
        from core.database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row[0].lower() == "wal", f"Expected WAL mode, got {row[0]}"

    @pytest.mark.asyncio
    async def test_busy_timeout_set_via_get_db(self):
        """Verify get_db() sets busy_timeout to a reasonable value."""
        from core.database import get_db
        async with get_db() as conn:
            cursor = await conn.execute("PRAGMA busy_timeout")
            row = await cursor.fetchone()
            assert row[0] >= 5000, f"Expected busy_timeout >= 5000, got {row[0]}"

    def test_metrics_collector_uses_busy_timeout(self):
        """Verify metrics_collector.py does not use bare aiosqlite.connect(DB_PATH)."""
        with open("core/metrics_collector.py", "r") as f:
            source = f.read()
        assert "PRAGMA busy_timeout" in source, (
            "metrics_collector.py must set busy_timeout on connections"
        )


class TestCollectMetricsScheduler:
    """Bug 4: collect_metrics should use 120s interval with coalesce."""

    def test_collect_metrics_interval_120s(self):
        """Verify collect_metrics is scheduled at 120s, not 30s or 60s."""
        with open("core/scheduler.py", "r") as f:
            source = f.read()
        assert "seconds=120" in source or "seconds = 120" in source, (
            "collect_metrics interval should be 120 seconds"
        )

    def test_collect_metrics_has_timeout(self):
        """Verify collect_metrics wraps inner logic with asyncio.wait_for timeout."""
        with open("core/metrics_collector.py", "r") as f:
            source = f.read()
        assert "wait_for" in source, (
            "collect_metrics should use asyncio.wait_for for timeout protection"
        )


class TestCompactionNoScanGuard:
    """Bug 5: DB compaction should not be deferred by scan_running check."""

    def test_no_scan_running_guard(self):
        """Verify run_db_compaction does not check for running scans."""
        with open("core/scheduler.py", "r") as f:
            source = f.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_db_compaction":
                func_source = ast.get_source_segment(source, node)
                assert "scan_running" not in func_source, (
                    "run_db_compaction should not check scan_running"
                )
                assert "compaction_deferred" not in func_source, (
                    "run_db_compaction should not defer compaction"
                )
                break
        else:
            pytest.fail("run_db_compaction function not found in scheduler.py")


class TestMCPConnectionHost:
    """Bug 6: MCP health check should use Docker service name, not localhost."""

    def test_mcp_info_uses_env_host(self):
        """Verify mcp_info.py reads MCP_HOST from env with correct default."""
        with open("api/routes/mcp_info.py", "r") as f:
            source = f.read()
        assert "MCP_HOST" in source, (
            "mcp_info.py should read MCP_HOST from environment"
        )
        assert "markflow-mcp" in source, (
            "MCP_HOST default should be 'markflow-mcp' (Docker service name)"
        )

    def test_docker_compose_has_mcp_host(self):
        """Verify docker-compose.yml sets MCP_HOST for the main app."""
        with open("docker-compose.yml", "r") as f:
            source = f.read()
        assert "MCP_HOST=markflow-mcp" in source or "MCP_HOST: markflow-mcp" in source, (
            "docker-compose.yml should set MCP_HOST=markflow-mcp for the main app"
        )


class TestAdminStats:
    """Bug 1: admin stats should not reference nonexistent columns."""

    @pytest.mark.asyncio
    async def test_admin_stats_returns_200(self, client):
        """GET /api/admin/stats should succeed without SQL errors."""
        response = await client.get("/api/admin/stats")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_stats_has_bulk_files(self, client):
        """Stats response should include bulk_files section."""
        response = await client.get("/api/admin/stats")
        data = response.json()
        assert "bulk_files" in data


class TestLogDownload:
    """Bug 7: Log download should use FileResponse with Content-Disposition."""

    @pytest.mark.asyncio
    async def test_download_invalid_filename_rejected(self, client):
        """Download endpoint should reject filenames not in whitelist."""
        response = await client.get("/api/logs/download/../../etc/passwd")
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_download_nonexistent_file(self, client):
        """Download endpoint should 404 for files that don't exist."""
        response = await client.get("/api/logs/download/nonexistent.log")
        # nonexistent.log is not in the whitelist, so should be 400
        assert response.status_code in (400, 404)


class TestOrphanCleanup:
    """Fix 8: Startup orphan job recovery."""

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_jobs(self):
        """Verify cleanup_orphaned_jobs cancels stuck jobs."""
        import aiosqlite
        from core.database import DB_PATH, cleanup_orphaned_jobs

        # Insert a fake stuck job
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute(
                """INSERT OR IGNORE INTO bulk_jobs
                   (id, status, source_path, output_path, created_at)
                   VALUES ('test_orphan_1', 'running', '/test', '/out', datetime('now'))"""
            )
            await conn.commit()

        # Run cleanup
        await cleanup_orphaned_jobs()

        # Verify it was cancelled
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT status FROM bulk_jobs WHERE id='test_orphan_1'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "cancelled"

            # Clean up test data
            await conn.execute("DELETE FROM bulk_jobs WHERE id='test_orphan_1'")
            await conn.commit()

    @pytest.mark.asyncio
    async def test_cleanup_does_not_touch_completed_jobs(self):
        """Verify cleanup leaves completed/cancelled jobs alone."""
        import aiosqlite
        from core.database import DB_PATH, cleanup_orphaned_jobs

        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute(
                """INSERT OR IGNORE INTO bulk_jobs
                   (id, status, source_path, output_path, created_at)
                   VALUES ('test_complete_1', 'completed', '/test', '/out', datetime('now'))"""
            )
            await conn.commit()

        await cleanup_orphaned_jobs()

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT status FROM bulk_jobs WHERE id='test_complete_1'"
            )
            row = await cursor.fetchone()
            assert row[0] == "completed"

            await conn.execute("DELETE FROM bulk_jobs WHERE id='test_complete_1'")
            await conn.commit()

    # v0.34.4 (BUG-012): orphan reaper extended to auto_conversion_runs.
    # Tests skip themselves when the test DB doesn't have the table —
    # the conftest fixture initializes a minimal schema. Production DB
    # always has it (created by the schema.py migration path).
    @staticmethod
    async def _has_auto_runs_table():
        import aiosqlite
        from core.database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='auto_conversion_runs'"
            ) as cur:
                return await cur.fetchone() is not None

    @pytest.mark.asyncio
    async def test_cleanup_reaps_orphaned_auto_conversion_runs(self):
        """Stuck auto_conversion_runs (status='running', completed_at=NULL)
        must be marked failed at startup, otherwise the auto-converter
        refuses to start new runs forever."""
        if not await self._has_auto_runs_table():
            pytest.skip("test DB lacks auto_conversion_runs table")
        import aiosqlite
        from core.database import DB_PATH, cleanup_orphaned_jobs

        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute(
                """INSERT INTO auto_conversion_runs
                   (scan_run_id, mode, was_override, files_discovered,
                    files_queued, batch_size_chosen, workers_chosen,
                    cpu_at_decision, memory_at_decision, reason,
                    bulk_job_id, started_at, status)
                   VALUES (?, 'immediate', 0, 100, 0, 50, 4, 5.0, 30.0,
                           'test fixture', ?, datetime('now'), 'running')""",
                ('test_scan_orphan_1', 'test_bulkjob_orphan_1')
            )
            await conn.commit()

        await cleanup_orphaned_jobs()

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """SELECT status, completed_at FROM auto_conversion_runs
                   WHERE scan_run_id = 'test_scan_orphan_1'"""
            )
            row = await cursor.fetchone()
            assert row is not None, "test fixture row went missing"
            assert row[0] == "failed", (
                f"orphaned auto_conversion_runs row should be failed, got {row[0]}"
            )
            assert row[1] is not None, (
                "completed_at must be set when reaping orphans"
            )

            await conn.execute(
                "DELETE FROM auto_conversion_runs WHERE scan_run_id = 'test_scan_orphan_1'"
            )
            await conn.commit()

    @pytest.mark.asyncio
    async def test_cleanup_does_not_touch_completed_auto_conversion_runs(self):
        """Already-completed auto_conversion_runs must not be re-marked."""
        if not await self._has_auto_runs_table():
            pytest.skip("test DB lacks auto_conversion_runs table")
        import aiosqlite
        from core.database import DB_PATH, cleanup_orphaned_jobs

        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute(
                """INSERT INTO auto_conversion_runs
                   (scan_run_id, mode, was_override, files_discovered,
                    files_queued, batch_size_chosen, workers_chosen,
                    cpu_at_decision, memory_at_decision, reason,
                    bulk_job_id, started_at, completed_at, status)
                   VALUES (?, 'immediate', 0, 100, 100, 50, 4, 5.0, 30.0,
                           'test fixture', ?, datetime('now'),
                           datetime('now'), 'completed')""",
                ('test_scan_complete_2', 'test_bulkjob_complete_2')
            )
            await conn.commit()

        await cleanup_orphaned_jobs()

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """SELECT status FROM auto_conversion_runs
                   WHERE scan_run_id = 'test_scan_complete_2'"""
            )
            row = await cursor.fetchone()
            assert row[0] == "completed", (
                f"already-completed run should not be touched, got {row[0]}"
            )

            await conn.execute(
                "DELETE FROM auto_conversion_runs WHERE scan_run_id = 'test_scan_complete_2'"
            )
            await conn.commit()


class TestStopBannerCSS:
    """Fix 9: Stop banner CSS specificity fix."""

    def test_stop_banner_hidden_override(self):
        """Verify .stop-banner[hidden] has display:none !important."""
        with open("static/markflow.css", "r") as f:
            source = f.read()
        assert ".stop-banner[hidden]" in source, (
            "markflow.css must have .stop-banner[hidden] rule"
        )
        assert "display: none !important" in source, (
            "markflow.css must override display with !important for hidden banner"
        )

    def test_stop_banner_js_uses_style_display(self):
        """Verify status.html uses style.display, not .hidden attribute."""
        with open("static/status.html", "r") as f:
            source = f.read()
        assert "style.display" in source, (
            "status.html should use style.display for stop banner toggle"
        )


class TestProgressTracker:
    """Fix 10: Rolling window ETA estimation (pre-existing, validated here)."""

    def test_progress_tracking_basic(self):
        """Completed count should track record_completion_sync calls."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA(total=100)
        for _ in range(50):
            tracker.record_completion_sync()
        snap = tracker.snapshot_sync()
        assert snap.completed == 50

    def test_zero_total_no_crash(self):
        """Zero total should not cause divide-by-zero."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA(total=0)
        snap = tracker.snapshot_sync()
        d = snap.to_dict()
        # percent is None when total is 0 (falsy)
        assert d.get("percent") is None or d["percent"] == 0.0

    def test_snapshot_to_dict(self):
        """Snapshot to_dict should return a JSON-serializable dict."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA(total=100)
        snap = tracker.snapshot_sync()
        d = snap.to_dict()
        assert isinstance(d, dict)
        assert "completed" in d
        assert "total" in d
        assert d["total"] == 100
        assert d["completed"] == 0

    def test_rate_calculation(self):
        """Rate should be positive after enough ticks."""
        from core.progress_tracker import RollingWindowETA
        tracker = RollingWindowETA(total=1000)
        for _ in range(5):
            tracker.record_completion_sync()
            time.sleep(0.01)
        snap = tracker.snapshot_sync()
        assert snap.files_per_second is not None
        assert snap.files_per_second > 0

    def test_format_eta(self):
        """format_eta should return human-readable strings."""
        from core.progress_tracker import format_eta
        assert format_eta(None) is None
        assert "remaining" in format_eta(30)
        assert "remaining" in format_eta(90)
        assert "h" in format_eta(7200)
