"""Single source of truth for resolving the output base directory.

Pre-v0.34.1 the codebase had **six** consumers of "where does converted
output live", each with its own resolution logic and import-time
constant capture:

    core/converter.py:65          OUTPUT_BASE = Path(os.getenv("OUTPUT_DIR", "output"))
    api/routes/batch.py:31        OUTPUT_BASE / batch_id (re-import)
    api/routes/history.py:269     OUTPUT_BASE / batch_id (re-import)
    core/lifecycle_manager.py:40  OUTPUT_REPO_ROOT = Path(os.getenv("BULK_OUTPUT_PATH", os.getenv("OUTPUT_DIR", "output")))
    mcp_server/tools.py:15        OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
    main.py:507                   _output_dir = os.getenv("OUTPUT_DIR", "output")

Drift was inevitable: Universal Storage Manager (v0.25.0) introduced a
DB-backed configured path, but only the bulk pipeline (v0.31.6) was
wired through it. The other five consumers kept reading the env var,
producing silent path divergence every time the operator changed the
output directory via the Storage page.

v0.34.1 unifies all six callers behind :func:`get_output_root` /
:func:`resolve_output_root`. Resolution priority:

    1. Storage Manager configured path (DB pref ``storage_output_path``)
    2. ``BULK_OUTPUT_PATH`` env var (legacy bulk-pipeline override)
    3. ``OUTPUT_DIR`` env var (legacy single-file override)
    4. Fallback ``Path("output")`` (relative; ``/app/output`` in container)

Re-resolution happens on every call — Storage Manager reconfigurations
take effect without a process restart for runtime consumers. (Static
mounts that bind at app startup, like ``/ocr-images``, still see the
env value at mount time and require a restart to pick up Storage
Manager changes — documented in gotchas.)

Author: v0.34.1 — closes BUG-001 through BUG-009 in ``docs/bug-log.md``.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def get_output_root() -> Path:
    """Resolve the current output base directory as a ``Path`` object.

    Pure function — no caching. Cheap (one env / DB-cache lookup).
    Always returns a Path; never None. The returned path may not exist
    on disk yet (e.g. fresh deploy before any conversion has run).
    """
    return Path(_resolve_str())


def get_output_root_str() -> str:
    """String form of :func:`get_output_root` — useful for FastAPI
    StaticFiles mount paths and logging context fields."""
    return _resolve_str()


def resolve_output_root_or_raise(*, label: str = "output_root") -> Path:
    """Like :func:`get_output_root` but raises ``RuntimeError`` if the
    result resolves to the legacy fallback ``output/`` (relative path).

    Use this in code paths that should not silently fall back to the
    pre-Storage-Manager default — e.g. the converter at runtime, where
    a relative ``output/`` would land at ``/app/output`` inside the
    container, outside the v0.25.0 write guard's allow-list.

    Note: the resolved path may still NOT exist on disk; this checks
    only that the resolution didn't fall through to the legacy default.
    """
    raw = _resolve_str()
    p = Path(raw)
    # If we resolved to the legacy fallback, surface that fact rather
    # than letting the caller silently write outside the configured root.
    if not p.is_absolute() or str(p) in ("output", "/app/output"):
        log.warning(
            "storage_paths.legacy_fallback_used",
            label=label,
            resolved=str(p),
            hint="Configure the output directory via the Storage page "
                 "(/storage.html) or set OUTPUT_DIR / BULK_OUTPUT_PATH "
                 "in your .env. Pre-v0.34.1 deployments may need a "
                 "Storage page revisit.",
        )
        raise RuntimeError(
            f"{label}: no Storage Manager output configured and no "
            f"OUTPUT_DIR/BULK_OUTPUT_PATH env override; refusing to "
            f"silently fall back to '{p}'. Set the output directory "
            f"on the Storage page or via env."
        )
    return p


def _resolve_str() -> str:
    """Internal resolver — returns the configured output root as a string.

    Storage Manager wins. We import ``get_output_path`` lazily because
    ``core.storage_manager`` is itself a consumer of preferences, and we
    don't want a top-level import here to create a circular dependency
    if storage_manager grows imports of converter/handlers later.
    """
    try:
        from core.storage_manager import get_output_path
        sm_path = get_output_path()
        if sm_path:
            return str(sm_path)
    except Exception:  # noqa: BLE001
        # Storage Manager not initialised yet (e.g. during early lifespan
        # before load_config_from_db ran). Fall through to env vars.
        pass

    env_bulk = os.environ.get("BULK_OUTPUT_PATH")
    if env_bulk:
        return env_bulk

    env_out = os.environ.get("OUTPUT_DIR")
    if env_out:
        return env_out

    return "output"


__all__ = [
    "get_output_root",
    "get_output_root_str",
    "resolve_output_root_or_raise",
]
