"""
structlog configuration for MarkFlow.

Dual-file JSON logging strategy:
  - Handler A: Operational log (logs/markflow.log)
    Always active. WARNING when normal, INFO when elevated/developer.
    Size-based rotation: 50 MB default, 5 backups.
  - Handler B: Debug trace log (logs/markflow-debug.log)
    Only active in developer mode. DEBUG level.
    Size-based rotation: 100 MB default, 3 backups.

Max sizes are configurable via environment variables:
  - LOG_MAX_SIZE_MB (default: 50)
  - DEBUG_LOG_MAX_SIZE_MB (default: 100)
  - LOG_BACKUP_COUNT (default: 5)
  - DEBUG_LOG_BACKUP_COUNT (default: 3)

Dynamic level switching via update_log_level() — no restart required.

Usage:
    from core.logging_config import configure_logging
    configure_logging("normal")       # call once at app startup

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
_current_level: str = "normal"

# Size-based rotation settings (configurable via env vars)
LOG_MAX_SIZE_MB = int(os.environ.get("LOG_MAX_SIZE_MB", "50"))
DEBUG_LOG_MAX_SIZE_MB = int(os.environ.get("DEBUG_LOG_MAX_SIZE_MB", "100"))
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
DEBUG_LOG_BACKUP_COUNT = int(os.environ.get("DEBUG_LOG_BACKUP_COUNT", "3"))

# Handler names for identification during hot-swap
_OPERATIONAL_HANDLER_NAME = "markflow_operational"
_DEBUG_HANDLER_NAME = "markflow_debug"

# Map preference strings to Python logging constants
LEVEL_MAP = {
    "normal": logging.WARNING,
    "elevated": logging.INFO,
    "developer": logging.DEBUG,
}

# Operational handler level: WARNING for normal, INFO for elevated/developer
_OPERATIONAL_LEVEL_MAP = {
    "normal": logging.WARNING,
    "elevated": logging.INFO,
    "developer": logging.INFO,
}

_logs_dir = Path(os.getenv("LOGS_DIR", "logs"))

# Keep a reference to the shared processors for formatter creation
_shared_processors: list = []


def _get_json_formatter():
    """Create a structlog JSON formatter using the shared processor chain."""
    return structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=_shared_processors,
    )


def _make_operational_handler(level: int) -> logging.handlers.RotatingFileHandler:
    """Create the operational log handler (logs/markflow.log).

    Size-based rotation: LOG_MAX_SIZE_MB (default 50 MB), LOG_BACKUP_COUNT (default 5).
    """
    _logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        _logs_dir / "markflow.log",
        maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.set_name(_OPERATIONAL_HANDLER_NAME)
    handler.setFormatter(_get_json_formatter())
    return handler


def _make_debug_handler() -> logging.handlers.RotatingFileHandler:
    """Create the debug trace log handler (logs/markflow-debug.log).

    Size-based rotation: DEBUG_LOG_MAX_SIZE_MB (default 100 MB), DEBUG_LOG_BACKUP_COUNT (default 3).
    """
    _logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        _logs_dir / "markflow-debug.log",
        maxBytes=DEBUG_LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=DEBUG_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.set_name(_DEBUG_HANDLER_NAME)
    handler.setFormatter(_get_json_formatter())
    return handler


def configure_logging(
    level: str = "normal",
    json_console: bool | None = None,
) -> None:
    """
    Configure structlog + stdlib logging. Idempotent.

    Args:
        level: MarkFlow log level preference ("normal", "elevated", "developer").
        json_console: If True, write JSON to stdout (for Docker). Falls back to
                      JSON_CONSOLE env var. Default: False.
    """
    global _configured, _current_level, _shared_processors
    if _configured:
        return
    _configured = True
    _current_level = level

    # Resolve json_console
    if json_console is None:
        json_console = os.getenv("JSON_CONSOLE", "false").lower() == "true"

    # Root level is always DEBUG so handlers control filtering
    root_level = LEVEL_MAP.get(level, logging.WARNING)

    # structlog processor chain
    _shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=_shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Build handlers
    handlers: list[logging.Handler] = []

    # Handler A: Operational log (always active)
    op_level = _OPERATIONAL_LEVEL_MAP.get(level, logging.WARNING)
    op_handler = _make_operational_handler(op_level)
    handlers.append(op_handler)

    # Handler B: Debug trace log (developer mode only)
    if level == "developer":
        debug_handler = _make_debug_handler()
        handlers.append(debug_handler)
        root_level = logging.DEBUG

    # Console handler
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(root_level)
    stream_handler.set_name("markflow_console")
    if json_console:
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=_shared_processors,
        )
    else:
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=_shared_processors,
        )
    stream_handler.setFormatter(console_formatter)
    handlers.append(stream_handler)

    # Configure stdlib root logger
    root = logging.getLogger()
    root.setLevel(root_level)
    for h in handlers:
        root.addHandler(h)

    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "aiosqlite", "PIL", "weasyprint",
                  "pdfminer", "pdfminer.pdfinterp", "pdfminer.psparser",
                  "pdfminer.pdfpage", "pdfminer.pdfdocument"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def update_log_level(new_level: str) -> None:
    """
    Hot-swap the active log level. Called when the preference is saved.

    1. Resolves new_level string to Python logging constant
    2. Updates root logger level
    3. Updates Handler A level (WARNING or INFO)
    4. Adds or removes Handler B (debug trace)
    5. Logs a WARNING-level event so the change is always visible
    """
    global _current_level

    if new_level not in LEVEL_MAP:
        return

    old_level = _current_level
    if old_level == new_level:
        return

    _current_level = new_level
    root = logging.getLogger()

    # Update root level
    root_level = LEVEL_MAP[new_level]
    root.setLevel(root_level)

    # Update operational handler level
    op_level = _OPERATIONAL_LEVEL_MAP.get(new_level, logging.WARNING)
    for handler in root.handlers:
        if getattr(handler, 'name', None) == _OPERATIONAL_HANDLER_NAME:
            handler.setLevel(op_level)
        elif getattr(handler, 'name', None) == "markflow_console":
            handler.setLevel(root_level)

    # Add or remove debug handler
    has_debug = any(
        getattr(h, 'name', None) == _DEBUG_HANDLER_NAME for h in root.handlers
    )

    if new_level == "developer" and not has_debug:
        debug_handler = _make_debug_handler()
        root.addHandler(debug_handler)
    elif new_level != "developer" and has_debug:
        for handler in root.handlers[:]:
            if getattr(handler, 'name', None) == _DEBUG_HANDLER_NAME:
                root.removeHandler(handler)
                handler.close()

    # Always log at WARNING so it appears in operational log regardless of level
    log = structlog.get_logger("core.logging_config")
    log.warning("log_level_changed", old_level=old_level, new_level=new_level)


def get_current_level() -> str:
    """Return the current MarkFlow log level string."""
    return _current_level


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
