"""dBase / FoxPro database engine — uses dbfread (pure Python)."""

from __future__ import annotations

from pathlib import Path

import structlog

from formats.database.engine import (
    ColumnInfo,
    DatabaseEngine,
    TableInfo,
)

log = structlog.get_logger(__name__)

_DBASE_TYPE_MAP = {
    "C": "CHARACTER",
    "N": "NUMERIC",
    "F": "FLOAT",
    "L": "LOGICAL",
    "D": "DATE",
    "T": "DATETIME",
    "M": "MEMO",
    "B": "BINARY",
    "G": "GENERAL",
    "I": "INTEGER",
    "Y": "CURRENCY",
    "0": "FLAGS",
}


class DBaseEngine(DatabaseEngine):
    """Extract schema and data from dBase/FoxPro .dbf files."""

    def __init__(self):
        self._table = None
        self._path: Path | None = None

    def open(self, path: Path, password: str | None = None) -> bool:
        try:
            if not path.exists():
                return False
            from dbfread import DBF
            self._table = DBF(str(path), load=False, encoding="latin-1")
            self._path = path
            _ = self._table.fields
            return True
        except Exception as exc:
            log.warning("dbase_open_failed", path=str(path), error=str(exc))
            self._table = None
            return False

    def list_tables(self) -> list[TableInfo]:
        assert self._table is not None
        name = self._path.stem if self._path else "data"
        row_count = 0
        for _ in self._table:
            row_count += 1
        col_count = len(self._table.fields)
        return [TableInfo(name=name, row_count=row_count, column_count=col_count)]

    def get_schema(self, table: str) -> list[ColumnInfo]:
        assert self._table is not None
        columns = []
        for f in self._table.fields:
            type_name = _DBASE_TYPE_MAP.get(f.type, f.type)
            if f.type in ("C", "N", "F") and f.length:
                if f.decimal_count:
                    type_name = f"{type_name}({f.length},{f.decimal_count})"
                else:
                    type_name = f"{type_name}({f.length})"
            columns.append(ColumnInfo(
                name=f.name,
                data_type=type_name,
                nullable=True,
                is_primary_key=False,
            ))
        return columns

    def get_row_count(self, table: str) -> int:
        assert self._table is not None
        count = 0
        for _ in self._table:
            count += 1
        return count

    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        assert self._table is not None
        cols = self.get_schema(table)
        header = [c.name for c in cols]
        result = [header]
        for i, record in enumerate(self._table):
            if i >= limit:
                break
            row = [str(record.get(c.name, "")) for c in cols]
            result.append(row)
        return result

    def close(self) -> None:
        self._table = None
