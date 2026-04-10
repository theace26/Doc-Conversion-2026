"""SQLite database engine — uses Python's built-in sqlite3 module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import structlog

from formats.database.engine import (
    ColumnInfo,
    DatabaseEngine,
    IndexInfo,
    RelationshipInfo,
    TableInfo,
)

log = structlog.get_logger(__name__)


class SQLiteEngine(DatabaseEngine):
    """Extract schema and data from SQLite databases."""

    def __init__(self):
        self._conn: sqlite3.Connection | None = None
        self._path: Path | None = None

    def open(self, path: Path, password: str | None = None) -> bool:
        try:
            if not path.exists():
                return False
            with open(path, "rb") as f:
                header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                if password:
                    return self._try_sqlcipher(path, password)
                return False
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.execute("SELECT count(*) FROM sqlite_master")
            self._conn = conn
            self._path = path
            return True
        except Exception as exc:
            log.warning("sqlite_open_failed", path=str(path), error=str(exc))
            return False

    def _try_sqlcipher(self, path: Path, password: str) -> bool:
        try:
            from pysqlcipher3 import dbapi2 as sqlcipher
            conn = sqlcipher.connect(str(path))
            conn.execute(f"PRAGMA key = '{password}'")
            conn.execute("SELECT count(*) FROM sqlite_master")
            self._conn = conn
            self._path = path
            return True
        except Exception:
            return False

    def list_tables(self) -> list[TableInfo]:
        assert self._conn is not None
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = []
        for (name,) in cursor.fetchall():
            row_count = self._conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            col_count = len(self._conn.execute(f'PRAGMA table_info("{name}")').fetchall())
            tables.append(TableInfo(name=name, row_count=row_count, column_count=col_count))
        return tables

    def get_schema(self, table: str) -> list[ColumnInfo]:
        assert self._conn is not None
        rows = self._conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = []
        for row in rows:
            columns.append(ColumnInfo(
                name=row[1],
                data_type=row[2] or "BLOB",
                nullable=not bool(row[3]),
                is_primary_key=bool(row[5]),
                default_value=row[4],
            ))
        return columns

    def get_row_count(self, table: str) -> int:
        assert self._conn is not None
        return self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        assert self._conn is not None
        cols = self.get_schema(table)
        header = [c.name for c in cols]
        rows = self._conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).fetchall()
        result = [header]
        for row in rows:
            result.append([str(v) if v is not None else "" for v in row])
        return result

    def get_relationships(self) -> list[RelationshipInfo]:
        assert self._conn is not None
        rels: list[RelationshipInfo] = []
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table_name,) in tables:
            fks = self._conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
            fk_groups: dict[int, list] = {}
            for fk in fks:
                fk_id = fk[0]
                fk_groups.setdefault(fk_id, []).append(fk)
            for fk_id, group in fk_groups.items():
                parent_table = group[0][2]
                child_cols = [g[3] for g in group]
                parent_cols = [g[4] for g in group]
                rels.append(RelationshipInfo(
                    name=f"fk_{table_name}_{parent_table}_{fk_id}",
                    parent_table=parent_table,
                    child_table=table_name,
                    parent_columns=parent_cols,
                    child_columns=child_cols,
                ))
        return rels

    def get_indexes(self) -> list[IndexInfo]:
        assert self._conn is not None
        indexes: list[IndexInfo] = []
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table_name,) in tables:
            idx_list = self._conn.execute(f'PRAGMA index_list("{table_name}")').fetchall()
            for idx in idx_list:
                idx_name = idx[1]
                is_unique = bool(idx[2])
                if idx_name.startswith("sqlite_autoindex_"):
                    continue
                idx_info = self._conn.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                columns = [row[2] for row in idx_info]
                indexes.append(IndexInfo(
                    name=idx_name,
                    table=table_name,
                    columns=columns,
                    unique=is_unique,
                ))
        return indexes

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
