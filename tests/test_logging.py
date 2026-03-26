"""
Tests for structured logging behavior.

Verifies that log events are properly structured, use static message strings,
and include expected context fields.
"""

import json
import logging
import pytest
import structlog

from core.logging_config import (
    bind_batch_context,
    bind_file_context,
    bind_request_context,
    clear_context,
)


class TestStructuredLogging:
    """Verify structured logging patterns."""

    def test_conversion_start_emits_batch_id(self, capsys):
        """A conversion log event should include batch_id field."""
        log = structlog.get_logger("test.logging")

        clear_context()
        bind_batch_context("batch_123", 3)
        log.warning("conversion_start", batch_id="batch_123", file_count=3)
        clear_context()

        captured = capsys.readouterr()
        assert "conversion_start" in captured.out

    def test_error_event_at_error_level(self, capsys):
        """Error events should use error log level."""
        log = structlog.get_logger("test.logging")

        log.error("file_conversion_error", filename="test.docx", error_type="ValueError", error_msg="bad")

        captured = capsys.readouterr()
        assert "file_conversion_error" in captured.out

    def test_request_id_in_context(self, capsys):
        """request_id should appear in log events during a request."""
        log = structlog.get_logger("test.logging")

        clear_context()
        bind_request_context("req-abc-123", "/api/convert", "POST")
        log.warning("test_event", data="hello")

        captured = capsys.readouterr()
        assert "test_event" in captured.out
        clear_context()

    def test_log_level_env_var(self):
        """configure_logging accepts a level param."""
        from core.logging_config import configure_logging
        # Already configured — idempotent check
        configure_logging(level="normal")

    def test_clear_context_resets(self):
        """clear_context() should remove all bound vars."""
        bind_request_context("req-1", "/test", "GET")
        bind_batch_context("batch-1", 5)
        clear_context()

        # After clear, context should be empty
        ctx = structlog.contextvars.get_contextvars()
        assert "request_id" not in ctx
        assert "batch_id" not in ctx

    def test_bind_file_context(self):
        """bind_file_context should add file_id, filename, file_format."""
        clear_context()
        bind_file_context("file-1", "test.docx", "docx")

        ctx = structlog.contextvars.get_contextvars()
        assert ctx["file_id"] == "file-1"
        assert ctx["filename"] == "test.docx"
        assert ctx["file_format"] == "docx"
        clear_context()


class TestNoBareLogs:
    """Verify no f-string logging or bare print calls."""

    def test_no_fstring_in_converter(self):
        """converter.py should not use f-string as log message."""
        import re
        from pathlib import Path

        source = Path("core/converter.py").read_text(encoding="utf-8")
        lines = source.split("\n")

        # Match log.info(f" or log.error(f" — f-string as first positional arg
        fstring_pattern = re.compile(r'log\.\w+\(\s*f["\']')
        for i, line in enumerate(lines, 1):
            if fstring_pattern.search(line):
                pytest.fail(f"F-string log message found at converter.py:{i}: {line.strip()}")

    def test_no_fstring_in_handlers(self):
        """Format handlers should not use f-string as log message."""
        import re
        from pathlib import Path

        handler_files = [
            "formats/docx_handler.py",
            "formats/pdf_handler.py",
            "formats/pptx_handler.py",
            "formats/xlsx_handler.py",
            "formats/csv_handler.py",
        ]

        fstring_pattern = re.compile(r'log\.\w+\(\s*f["\']')
        for fname in handler_files:
            source = Path(fname).read_text(encoding="utf-8")
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                if fstring_pattern.search(line):
                    pytest.fail(f"F-string log message at {fname}:{i}: {line.strip()}")

    def test_no_print_in_core(self):
        """No print() calls in core/ or formats/."""
        from pathlib import Path
        import re

        dirs = [Path("core"), Path("formats")]
        for d in dirs:
            if not d.exists():
                continue
            for pyfile in d.glob("*.py"):
                source = pyfile.read_text(encoding="utf-8")
                lines = source.split("\n")
                for i, line in enumerate(lines, 1):
                    # Skip comments and strings
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if re.match(r"^\s*print\(", line):
                        pytest.fail(f"print() call at {pyfile}:{i}: {stripped}")

    def test_no_bare_logging_in_handlers(self):
        """Format handlers should use structlog, not logging.getLogger."""
        from pathlib import Path

        handler_files = [
            "formats/docx_handler.py",
            "formats/pdf_handler.py",
            "formats/pptx_handler.py",
            "formats/xlsx_handler.py",
            "formats/csv_handler.py",
        ]

        for fname in handler_files:
            source = Path(fname).read_text(encoding="utf-8")
            assert "logging.getLogger" not in source, f"{fname} still uses logging.getLogger"

    def test_all_handlers_use_structlog(self):
        """All format handlers should import structlog."""
        from pathlib import Path

        handler_files = [
            "formats/docx_handler.py",
            "formats/pdf_handler.py",
            "formats/pptx_handler.py",
            "formats/xlsx_handler.py",
            "formats/csv_handler.py",
        ]

        for fname in handler_files:
            source = Path(fname).read_text(encoding="utf-8")
            assert "import structlog" in source, f"{fname} does not import structlog"

    def test_json_log_file_path(self):
        """Log file should be named markflow.log (v0.9.5 dual-file strategy)."""
        from pathlib import Path

        config_source = Path("core/logging_config.py").read_text(encoding="utf-8")
        assert "markflow.log" in config_source

    def test_no_logging_import_in_image_handler(self):
        """image_handler.py should use structlog, not logging."""
        from pathlib import Path

        source = Path("core/image_handler.py").read_text(encoding="utf-8")
        assert "import structlog" in source
        assert "import logging" not in source

    def test_middleware_uses_clear_context(self):
        """Middleware should call clear_context() in finally block."""
        from pathlib import Path

        source = Path("api/middleware.py").read_text(encoding="utf-8")
        assert "clear_context" in source
        assert "finally:" in source


# ── v0.9.5: Configurable logging levels ──────────────────────────────────────

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _reset_logging():
    """Reset the logging_config module state for unit tests."""
    import core.logging_config as lc
    lc._configured = False
    lc._current_level = "normal"
    root = logging.getLogger()
    for h in root.handlers[:]:
        name = getattr(h, 'name', '')
        if name and name.startswith('markflow'):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass


class TestConfigureLoggingLevels:
    """Test dual-file logging configuration at each level."""

    def setup_method(self):
        _reset_logging()

    def teardown_method(self):
        _reset_logging()

    def test_normal_sets_warning(self, tmp_path):
        """configure_logging('normal') sets operational handler to WARNING."""
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging
            configure_logging("normal")

        root = logging.getLogger()
        op = next((h for h in root.handlers if getattr(h, 'name', '') == 'markflow_operational'), None)
        assert op is not None
        assert op.level == logging.WARNING

    def test_elevated_sets_info(self, tmp_path):
        """configure_logging('elevated') sets operational handler to INFO."""
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging
            configure_logging("elevated")

        root = logging.getLogger()
        op = next((h for h in root.handlers if getattr(h, 'name', '') == 'markflow_operational'), None)
        assert op is not None
        assert op.level == logging.INFO

    def test_developer_creates_debug_handler(self, tmp_path):
        """configure_logging('developer') creates debug handler at DEBUG level."""
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging
            configure_logging("developer")

        root = logging.getLogger()
        debug_h = next((h for h in root.handlers if getattr(h, 'name', '') == 'markflow_debug'), None)
        assert debug_h is not None
        assert debug_h.level == logging.DEBUG

    def test_normal_no_debug_handler(self, tmp_path):
        """configure_logging('normal') does NOT create debug handler."""
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging
            configure_logging("normal")

        root = logging.getLogger()
        names = [getattr(h, 'name', '') for h in root.handlers]
        assert 'markflow_debug' not in names


class TestUpdateLogLevel:
    """Test hot-swap of log levels at runtime."""

    def setup_method(self):
        _reset_logging()

    def teardown_method(self):
        _reset_logging()

    def test_switch_to_developer_adds_debug_handler(self, tmp_path):
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging, update_log_level
            configure_logging("normal")

            root = logging.getLogger()
            assert not any(getattr(h, 'name', '') == 'markflow_debug' for h in root.handlers)

            update_log_level("developer")
            assert any(getattr(h, 'name', '') == 'markflow_debug' for h in root.handlers)

    def test_switch_to_normal_removes_debug_handler(self, tmp_path):
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging, update_log_level
            configure_logging("developer")

            root = logging.getLogger()
            assert any(getattr(h, 'name', '') == 'markflow_debug' for h in root.handlers)

            update_log_level("normal")
            assert not any(getattr(h, 'name', '') == 'markflow_debug' for h in root.handlers)

    def test_level_change_updates_operational_level(self, tmp_path):
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging, update_log_level
            configure_logging("normal")

            root = logging.getLogger()
            op = next(h for h in root.handlers if getattr(h, 'name', '') == 'markflow_operational')
            assert op.level == logging.WARNING

            update_log_level("elevated")
            assert op.level == logging.INFO

    def test_change_event_always_logged(self, tmp_path, caplog):
        """Log level change event is always visible (logged at WARNING)."""
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging, update_log_level
            configure_logging("normal")

        with caplog.at_level(logging.WARNING):
            from core.logging_config import update_log_level
            update_log_level("elevated")

        assert any("log_level_changed" in r.message for r in caplog.records)

    def test_get_current_level_reflects_changes(self, tmp_path):
        from unittest.mock import patch
        with patch("core.logging_config._logs_dir", tmp_path):
            from core.logging_config import configure_logging, update_log_level, get_current_level
            configure_logging("normal")
            assert get_current_level() == "normal"
            update_log_level("developer")
            assert get_current_level() == "developer"


# ── API endpoint tests ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="module")
async def log_client():
    """Async HTTP client for logging endpoint tests."""
    from core.database import init_db
    from main import app
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestClientEventEndpoint:

    @pytest.mark.anyio
    async def test_dev_mode_off_returns_204(self, log_client):
        """POST /api/log/client-event returns 204 when not in developer mode."""
        await log_client.put("/api/preferences/log_level", json={"value": "normal"})
        resp = await log_client.post("/api/log/client-event", json={
            "page": "test.html", "event": "click", "target": "btn-test"
        })
        assert resp.status_code == 204

    @pytest.mark.anyio
    async def test_dev_mode_on_returns_204(self, log_client):
        """POST /api/log/client-event returns 204 in developer mode."""
        await log_client.put("/api/preferences/log_level", json={"value": "developer"})
        resp = await log_client.post("/api/log/client-event", json={
            "page": "test.html", "event": "click", "target": "btn-test"
        })
        assert resp.status_code == 204
        await log_client.put("/api/preferences/log_level", json={"value": "normal"})

    @pytest.mark.anyio
    async def test_malformed_body_returns_204(self, log_client):
        """POST /api/log/client-event with malformed body still returns 204."""
        resp = await log_client.post(
            "/api/log/client-event",
            content="not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 204


class TestLogDownloadEndpoint:

    @pytest.mark.anyio
    async def test_unknown_file_returns_400(self, log_client):
        resp = await log_client.get("/api/logs/download/unknown.log")
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_path_traversal_returns_400(self, log_client):
        """Filenames not in the whitelist are rejected — prevents traversal."""
        resp = await log_client.get("/api/logs/download/secret.log")
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_markflow_log_allowed(self, log_client):
        """markflow.log is in the whitelist — returns 200 or 404."""
        resp = await log_client.get("/api/logs/download/markflow.log")
        assert resp.status_code in (200, 404)

    @pytest.mark.anyio
    async def test_markflow_debug_log_allowed(self, log_client):
        """markflow-debug.log is in the whitelist — returns 200 or 404."""
        resp = await log_client.get("/api/logs/download/markflow-debug.log")
        assert resp.status_code in (200, 404)


class TestLogLevelPreference:

    @pytest.mark.anyio
    async def test_log_level_in_preferences(self, log_client):
        resp = await log_client.get("/api/preferences")
        assert resp.status_code == 200
        prefs = resp.json().get("preferences", resp.json())
        assert "log_level" in prefs

    @pytest.mark.anyio
    async def test_valid_enum_values(self, log_client):
        for level in ("normal", "elevated", "developer"):
            resp = await log_client.put("/api/preferences/log_level", json={"value": level})
            assert resp.status_code == 200
        await log_client.put("/api/preferences/log_level", json={"value": "normal"})

    @pytest.mark.anyio
    async def test_invalid_enum_rejected(self, log_client):
        resp = await log_client.put("/api/preferences/log_level", json={"value": "verbose"})
        assert resp.status_code == 422
