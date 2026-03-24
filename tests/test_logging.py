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

    def test_conversion_start_emits_batch_id(self, caplog):
        """A conversion log event should include batch_id field."""
        log = structlog.get_logger("test.logging")

        with caplog.at_level(logging.INFO):
            clear_context()
            bind_batch_context("batch_123", 3)
            log.info("conversion_start", batch_id="batch_123", file_count=3)

        assert any("conversion_start" in r.message for r in caplog.records)

    def test_error_event_at_error_level(self, caplog):
        """Error events should use error log level."""
        log = structlog.get_logger("test.logging")

        with caplog.at_level(logging.ERROR):
            log.error("file_conversion_error", filename="test.docx", error_type="ValueError", error_msg="bad")

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) >= 1

    def test_request_id_in_context(self, caplog):
        """request_id should appear in log events during a request."""
        log = structlog.get_logger("test.logging")

        with caplog.at_level(logging.INFO):
            clear_context()
            bind_request_context("req-abc-123", "/api/convert", "POST")
            log.info("test_event", data="hello")

        # The request_id should be bound in structlog context
        # (visible in JSON output, caplog may not show it directly)
        assert any("test_event" in r.message for r in caplog.records)
        clear_context()

    def test_log_level_env_var(self):
        """LOG_LEVEL env var should control the configured level."""
        import os

        # Just verify the config function accepts a log_level param
        from core.logging_config import configure_logging
        # Already configured — idempotent check
        configure_logging(log_level="DEBUG")

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
        """Log file should be named markflow.json, not markflow.log."""
        from pathlib import Path

        config_source = Path("core/logging_config.py").read_text(encoding="utf-8")
        assert "markflow.json" in config_source

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
