"""
structlog configuration for MarkFlow.

JSON-format structured logging with:
  - request_id / batch_id / file_id propagation via contextvars
  - Rotating file handler: logs/markflow.json (10MB, 5 backups)
  - stdout output for Docker log aggregation
  - LOG_LEVEL env var (default INFO); DEBUG=true also enables debug

Log entry fields: timestamp, level, logger, request_id, batch_id, file_name,
                  stage, duration_ms, status, message, and any extras.

Usage:
    from core.logging_config import configure_logging
    configure_logging()          # call once at app startup

    import structlog
    log = structlog.get_logger(__name__)
    log.info("stage_complete", stage="extract_text", duration_ms=123)
"""

import logging
import logging.handlers
import os
from pathlib import Path

import structlog

_configured = False


def configure_logging(
    log_level: str | None = None,
    json_console: bool | None = None,
) -> None:
    """
    Configure structlog + stdlib logging. Idempotent.

    Args:
        log_level: Override log level (DEBUG/INFO/WARNING/ERROR). Falls back to
                   LOG_LEVEL env var, then DEBUG env var, then INFO.
        json_console: If True, write JSON to stdout (for Docker). Falls back to
                      JSON_CONSOLE env var. Default: False.
    """
    global _configured
    if _configured:
        return
    _configured = True

    # ── Resolve log level ───────────────────────────────────────────────────
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "").upper()
    if not log_level:
        debug = os.getenv("DEBUG", "false").lower() == "true"
        log_level = "DEBUG" if debug else "INFO"

    numeric_level = getattr(logging, log_level, logging.INFO)

    # ── Resolve json_console ────────────────────────────────────────────────
    if json_console is None:
        json_console = os.getenv("JSON_CONSOLE", "false").lower() == "true"

    # ── Stdlib handler: rotating JSON file ──────────────────────────────────
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "markflow.json",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)

    # ── Stdlib handler: stdout ──────────────────────────────────────────────
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(numeric_level)

    # Basic stdlib config (structlog chains into it)
    logging.basicConfig(
        level=numeric_level,
        handlers=[file_handler, stream_handler],
        format="%(message)s",
    )

    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "aiosqlite", "PIL", "weasyprint"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── structlog processor chain ───────────────────────────────────────────
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # JSON renderer for file handler (always JSON)
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    file_handler.setFormatter(json_formatter)

    # Console: JSON if json_console, else human-readable
    if json_console:
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    else:
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=shared_processors,
        )
    stream_handler.setFormatter(console_formatter)


# ── Context binding helpers ─────────────────────────────────────────────────


def bind_request_context(request_id: str, path: str, method: str) -> None:
    """Bind request-scoped context vars. Call from middleware on request start."""
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        http_path=path,
        http_method=method,
    )


def bind_batch_context(batch_id: str, file_count: int) -> None:
    """Bind batch-scoped context vars. Call from ConversionOrchestrator."""
    structlog.contextvars.bind_contextvars(
        batch_id=batch_id,
        file_count=file_count,
    )


def bind_file_context(file_id: str, filename: str, fmt: str) -> None:
    """Bind per-file context vars. Call per-file inside batch loop."""
    structlog.contextvars.bind_contextvars(
        file_id=file_id,
        filename=filename,
        file_format=fmt,
    )


def clear_context() -> None:
    """Clear all bound context vars. Call at end of request in middleware."""
    structlog.contextvars.clear_contextvars()
