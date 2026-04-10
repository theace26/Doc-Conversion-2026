"""QuickBooks engine — best-effort binary header parsing for .qbb/.qbw files."""

from __future__ import annotations

import re
from pathlib import Path

import structlog

from formats.database.engine import (
    ColumnInfo,
    DatabaseEngine,
    TableInfo,
)

log = structlog.get_logger(__name__)

_COMPANY_NAME_SCAN_RANGE = (0, 4096)


class QuickBooksEngine(DatabaseEngine):
    """Best-effort extraction from QuickBooks .qbb/.qbw files."""

    def __init__(self):
        self._path: Path | None = None
        self._header_bytes: bytes = b""
        self._company_name: str = ""
        self._qb_version: str = ""
        self._encrypted: bool = False
        self._tables_found: list[TableInfo] = []
        self._is_metadata_only: bool = True

    @property
    def is_metadata_only(self) -> bool:
        return self._is_metadata_only

    @property
    def file_format(self) -> str:
        if self._path:
            return self._path.suffix.lstrip(".").lower()
        return ""

    @property
    def company_name(self) -> str:
        return self._company_name

    @property
    def qb_version(self) -> str:
        return self._qb_version

    @property
    def encrypted(self) -> bool:
        return self._encrypted

    def open(self, path: Path, password: str | None = None) -> bool:
        if not path.exists():
            return False
        try:
            self._path = path
            with open(path, "rb") as f:
                self._header_bytes = f.read(8192)
            self._parse_header()
            self._scan_for_tables()
            return True
        except Exception as exc:
            log.warning("quickbooks_open_failed", path=str(path), error=str(exc))
            return False

    def _parse_header(self) -> None:
        start, end = _COMPANY_NAME_SCAN_RANGE
        chunk = self._header_bytes[start:end]
        strings = re.findall(rb"[ -~]{8,100}", chunk)
        if strings:
            for s in strings:
                decoded = s.decode("ascii", errors="replace").strip()
                if not any(x in decoded.lower() for x in (":\\", "/", ".dll", ".exe", "quickbooks")):
                    self._company_name = decoded
                    break
        if len(self._header_bytes) > 512:
            byte_set = set(self._header_bytes[256:512])
            if len(byte_set) > 240:
                self._encrypted = True

    def _scan_for_tables(self) -> None:
        self._is_metadata_only = True

    def list_tables(self) -> list[TableInfo]:
        return self._tables_found

    def get_schema(self, table: str) -> list[ColumnInfo]:
        return []

    def get_row_count(self, table: str) -> int:
        return 0

    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        return []

    def close(self) -> None:
        self._header_bytes = b""
        self._tables_found = []
