"""Detect which database engines are available on this system."""

from __future__ import annotations

import shutil

import structlog

log = structlog.get_logger(__name__)


def detect_database_engines() -> dict[str, bool]:
    """Probe for available database engine backends."""
    caps: dict[str, bool] = {}
    caps["sqlite3"] = True
    caps["mdbtools"] = shutil.which("mdb-tables") is not None
    caps["pyodbc_mdbtools"] = _check_pyodbc_mdbtools()
    caps["jackcess"] = _check_jackcess()
    caps["dbfread"] = _check_import("dbfread")
    caps["pysqlcipher3"] = _check_import("pysqlcipher3")
    log.info("database_engines_detected", **caps)
    return caps


def _check_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_pyodbc_mdbtools() -> bool:
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        return "MDBTools" in drivers
    except Exception:
        return False


def _check_jackcess() -> bool:
    from pathlib import Path
    if not shutil.which("java"):
        return False
    jar_candidates = [
        Path("/opt/jackcess/jackcess-cli.jar"),
        Path("/app/lib/jackcess-cli.jar"),
    ]
    return any(p.exists() for p in jar_candidates)
