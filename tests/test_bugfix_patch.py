"""Tests for v0.12.0a bugfix patch.

Validates fixes for:
- Bug 2: structlog double event argument
- Bug 3: SQLite WAL mode + busy_timeout on all connections
- Bug 4: collect_metrics interval and timeout
- Bug 5: DB compaction no longer deferred by scan_running guard
- Bug 6: MCP connection uses Docker service name
"""
import ast

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
        # The _db() helper should exist and set busy_timeout
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

        # Extract just the run_db_compaction function
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
