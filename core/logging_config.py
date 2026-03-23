"""
structlog configuration for MarkFlow.

JSON-format structured logging with:
  - request_id propagation via contextvars
  - Rotating file handler: logs/markflow.log (10MB, 5 backups)
  - stdout output for Docker log aggregation
  - DEBUG level when DEBUG=true env var, else INFO

Log entry fields: timestamp, level, request_id, batch_id, file_name,
                  stage, duration_ms, status, message, and any extras.

Usage:
    from core.logging_config import configure_logging
    configure_logging()          # call once at app startup

    import structlog
    log = structlog.get_logger(__name__)
    log.info("stage.complete", stage="extract_text", duration_ms=123)
"""

import logging
import logging.handlers
import os
from pathlib import Path

import structlog

_configured = False


def configure_logging() -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    global _configured
    if _configured:
        return
    _configured = True

    debug = os.getenv("DEBUG", "false").lower() == "true"
    log_level = logging.DEBUG if debug else logging.INFO

    # ── Stdlib handler: rotating file ────────────────────────────────────────
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "markflow.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)

    # ── Stdlib handler: stdout ────────────────────────────────────────────────
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)

    # Basic stdlib config (structlog chains into it)
    logging.basicConfig(
        level=log_level,
        handlers=[file_handler, stream_handler],
        format="%(message)s",
    )

    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── structlog processor chain ─────────────────────────────────────────────
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
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

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    for handler in logging.root.handlers:
        handler.setFormatter(formatter)
