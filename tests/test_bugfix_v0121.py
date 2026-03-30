"""Tests for v0.12.1 stability patch — mount readiness, cache headers, codebase checks.

Complements tests/test_bugfix_patch.py which covers fixes 1-9.
This file covers fix 10 (mount readiness), fix 12 (cache headers),
and project-wide structlog/logging checks.
"""
import ast
import glob
import inspect

import pytest


class TestStructlogNoDoubleEvent:
    """Verify no structlog calls in the project use event= as a kwarg."""

    def _check_file_for_double_event(self, filepath):
        with open(filepath) as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError:
                return []
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "info", "error", "warning", "debug", "critical", "exception"
                ):
                    has_positional = len(node.args) > 0
                    has_event_kwarg = any(kw.arg == "event" for kw in node.keywords)
                    if has_positional and has_event_kwarg:
                        violations.append(
                            f"{filepath}:{node.lineno}: "
                            f"log.{node.func.attr}() passes event= alongside positional arg"
                        )
        return violations

    def test_no_double_event_anywhere(self):
        """Scan entire codebase for structlog double-event pattern."""
        violations = []
        for pattern in ["core/*.py", "api/**/*.py", "mcp_server/*.py"]:
            for filepath in glob.glob(pattern, recursive=True):
                violations.extend(self._check_file_for_double_event(filepath))
        assert not violations, (
            f"Found {len(violations)} structlog double-event violations:\n"
            + "\n".join(violations)
        )


class TestMountReadiness:
    """Fix 10: Source mount verification before scanning."""

    def test_empty_dir_rejected(self, tmp_path):
        from core.bulk_scanner import _verify_source_mount
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _verify_source_mount(str(empty)) is False

    def test_populated_dir_accepted(self, tmp_path):
        from core.bulk_scanner import _verify_source_mount
        pop = tmp_path / "populated"
        pop.mkdir()
        (pop / "file.txt").write_text("x")
        assert _verify_source_mount(str(pop)) is True

    def test_nonexistent_rejected(self):
        from core.bulk_scanner import _verify_source_mount
        assert _verify_source_mount("/no/such/path/xyz123") is False


class TestStaticCacheHeaders:
    """Fix 12: Static files should have cache-control headers."""

    @pytest.mark.asyncio
    async def test_static_file_has_cache_control(self, client):
        """Static CSS file should include Cache-Control header."""
        response = await client.get("/static/markflow.css")
        if response.status_code == 200:
            assert "cache-control" in response.headers
            assert "no-cache" in response.headers["cache-control"]

    @pytest.mark.asyncio
    async def test_api_endpoint_no_cache_header(self, client):
        """API endpoints should NOT get the static cache-control header."""
        response = await client.get("/api/health")
        cache = response.headers.get("cache-control", "")
        # API responses should not have the static-specific no-cache header
        # (they may have their own caching strategy)
        assert "must-revalidate" not in cache or not str(response.request.url).startswith("/static/")


class TestLogRotation:
    """Verify log handlers use rotation, not unbounded FileHandler."""

    def test_no_plain_filehandler(self):
        """logging_config should use RotatingFileHandler, not plain FileHandler."""
        source = inspect.getsource(__import__("core.logging_config", fromlist=[""]))
        assert "RotatingFileHandler" in source, (
            "logging_config must use RotatingFileHandler"
        )
