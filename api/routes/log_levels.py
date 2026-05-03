"""Per-subsystem log level configuration API (new-UX operator tooling).

GET  /api/log-levels        — returns all registered Python loggers and their current level
PUT  /api/log-levels        — sets the level for one logger via logging.getLogger(name).setLevel()

Persistence: in-memory only for this first cut. The level setting survives for
the lifetime of the running container. On restart, the logger tree reverts to
whatever configure_logging() set. A persistent layer (DB pref per logger) can
be added later without changing this API.

Admin-gated.
"""

from __future__ import annotations

import logging

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import AuthenticatedUser, UserRole, require_role

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/log-levels", tags=["log-levels"])

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# Map level name -> numeric constant
_LEVEL_INT = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# Loggers we want to surface even when they have no active handlers / are
# not yet populated in the logging manager dict (i.e. they exist in code
# but nothing has called getLogger on them yet in this run).
_INTERESTING_PREFIXES = (
    "core.",
    "api.",
    "web_app.",
    "scripts.",
    "markflow",
    "uvicorn",
    "fastapi",
)


def _level_name(logger: logging.Logger) -> str:
    """Return the effective level name for *logger*.

    If the logger's own level is NOTSET (0), climb the hierarchy to find
    the first ancestor with a non-NOTSET level, exactly as Python's
    getEffectiveLevel() does, but return the string label."""
    lvl = logger.level
    if lvl != logging.NOTSET:
        return logging.getLevelName(lvl)
    return logging.getLevelName(logger.getEffectiveLevel())


def _own_level_name(logger: logging.Logger) -> str:
    """Return the logger's *own* level (NOTSET if inherited)."""
    if logger.level == logging.NOTSET:
        return "NOTSET"
    return logging.getLevelName(logger.level)


def _collect_loggers() -> list[dict]:
    """Return a sorted list of logger dicts for all loggers in the manager.

    Each dict has: name, effective_level, own_level, namespace (top-level prefix).
    """
    manager = logging.Logger.manager
    all_names: list[str] = list(manager.loggerDict.keys())  # type: ignore[attr-defined]

    # Always include the root logger.
    result: list[dict] = []

    seen: set[str] = set()

    def _add(name: str | None, lgr: logging.Logger) -> None:
        key = name or "root"
        if key in seen:
            return
        seen.add(key)
        ns = (name or "root").split(".")[0] if name else "root"
        result.append({
            "name": key,
            "effective_level": _level_name(lgr),
            "own_level": _own_level_name(lgr),
            "namespace": ns,
        })

    _add(None, logging.getLogger())

    for name in sorted(all_names):
        obj = manager.loggerDict.get(name)  # type: ignore[attr-defined]
        # Can be a Logger or a PlaceHolder.
        if isinstance(obj, logging.Logger):
            _add(name, obj)
        else:
            # PlaceHolder — include it as a virtual entry so operators can
            # see the namespace even if no code has logged through it yet.
            lgr = logging.getLogger(name)
            _add(name, lgr)

    # Sort: root first, then by name.
    result.sort(key=lambda d: ("" if d["name"] == "root" else d["name"]))
    return result


# ── GET ───────────────────────────────────────────────────────────────────────


@router.get("")
async def list_log_levels(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Return current level for every registered Python logger."""
    loggers = _collect_loggers()
    return {"loggers": loggers}


# ── PUT ───────────────────────────────────────────────────────────────────────


class LevelUpdate(BaseModel):
    logger: str
    level: str  # DEBUG | INFO | WARNING | ERROR | CRITICAL


@router.put("")
async def set_log_level(
    body: LevelUpdate,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Set the level for a single logger (in-memory, no restart required).

    Pass ``logger="root"`` to adjust the root logger.
    Pass level ``"NOTSET"`` to clear an override and revert to inherited level.
    """
    level_upper = body.level.strip().upper()
    valid_with_notset = _VALID_LEVELS | {"NOTSET"}
    if level_upper not in valid_with_notset:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level '{body.level}'. Valid: {sorted(valid_with_notset)}",
        )

    name = body.logger.strip()
    if name == "root":
        lgr = logging.getLogger()
    else:
        if not name:
            raise HTTPException(status_code=400, detail="logger name must not be empty")
        lgr = logging.getLogger(name)

    if level_upper == "NOTSET":
        lgr.setLevel(logging.NOTSET)
    else:
        lgr.setLevel(_LEVEL_INT[level_upper])

    log.info(
        "log_levels.set",
        user=user.email,
        logger=name,
        level=level_upper,
    )

    return {
        "logger": name,
        "level": level_upper,
        "effective_level": _level_name(lgr),
        "own_level": _own_level_name(lgr),
    }
