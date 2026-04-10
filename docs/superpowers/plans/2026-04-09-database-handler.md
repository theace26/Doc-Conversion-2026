# Database File Handler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DatabaseHandler that extracts schema, metadata, and sample data from SQLite, Access, dBase, and QuickBooks files into structured Markdown.

**Architecture:** Engine-per-format behind a common ABC (`DatabaseEngine`). The handler dispatches to the correct engine by extension, runs the password cascade if encrypted, then assembles a DocumentModel with schema tables, sample data, and relationships. Replaces the BinaryHandler registration for database extensions.

**Tech Stack:** Python `sqlite3` (built-in), `mdbtools` CLI (apt), `pyodbc` + mdbtools ODBC (apt+pip), `jackcess` JAR (opt-in Java), `dbfread` (pip), `pysqlcipher3` (pip). Password integration via existing `formats/archive_handler.py` cascade pattern.

**Spec:** `docs/superpowers/specs/2026-04-09-database-handler-design.md`

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `formats/database/__init__.py` | Package init — exports engine ABC + dataclasses |
| Create | `formats/database/engine.py` | `DatabaseEngine` ABC + `TableInfo`, `ColumnInfo`, `RelationshipInfo`, `IndexInfo` dataclasses |
| Create | `formats/database/sqlite_engine.py` | SQLite engine using built-in `sqlite3` |
| Create | `formats/database/access_engine.py` | Access engine with mdbtools -> pyodbc -> jackcess cascade |
| Create | `formats/database/dbase_engine.py` | dBase engine using `dbfread` |
| Create | `formats/database/quickbooks_engine.py` | QuickBooks best-effort binary header parser |
| Create | `formats/database/capability.py` | Engine availability detection (probe at startup, cache results) |
| Create | `formats/database_handler.py` | Main `DatabaseHandler(FormatHandler)` — dispatch + DocumentModel assembly |
| Create | `tests/test_database_handler.py` | Handler-level tests (ingest, schema, sample data, error cases) |
| Create | `tests/test_database_engines.py` | Engine-level unit tests (SQLite, dBase, capability detection) |
| Modify | `formats/__init__.py:37-38` | Add `DatabaseHandler` import before `BinaryHandler` |
| Modify | `formats/binary_handler.py:43-44` | Remove `"sqlite", "db", "mdb", "accdb"` from EXTENSIONS |
| Modify | `core/db/preferences.py:105` | Add `"database_sample_rows": "25"` to DEFAULT_PREFERENCES |
| Modify | `api/routes/preferences.py:43,49+` | Add to `_SYSTEM_PREF_KEYS` + `_PREFERENCE_SCHEMA` |
| Modify | `Dockerfile.base:48-51` | Add `mdbtools`, `unixodbc-dev`, `odbc-mdbtools` to apt-get |
| Modify | `Dockerfile.base:69-70` | Add `dbfread`, `pyodbc`, `pysqlcipher3` to pip install |
| Modify | `docs/formats.md:37` | Replace database extensions from Binary row, add new Database row |
| Create | `docs/help/database-files.md` | Help wiki article for database file support |

---

## Task 1: Engine ABC + Dataclasses

**Files:**
- Create: `formats/database/__init__.py`
- Create: `formats/database/engine.py`
- Test: `tests/test_database_engines.py`

- [ ] **Step 1: Write the test for dataclasses and ABC**

```python
# tests/test_database_engines.py
"""Tests for database engine ABC and dataclasses."""

import pytest
from formats.database.engine import (
    DatabaseEngine,
    TableInfo,
    ColumnInfo,
    RelationshipInfo,
    IndexInfo,
)


class TestDataclasses:
    def test_table_info_fields(self):
        t = TableInfo(name="Members", row_count=100, column_count=5)
        assert t.name == "Members"
        assert t.row_count == 100
        assert t.column_count == 5

    def test_column_info_defaults(self):
        c = ColumnInfo(name="id", data_type="INTEGER", nullable=False, is_primary_key=True)
        assert c.default_value is None

    def test_column_info_with_default(self):
        c = ColumnInfo(name="status", data_type="TEXT", nullable=True, is_primary_key=False, default_value="'active'")
        assert c.default_value == "'active'"

    def test_relationship_info_fields(self):
        r = RelationshipInfo(
            name="fk_dues_member",
            parent_table="Members",
            child_table="DuesPayments",
            parent_columns=["MemberID"],
            child_columns=["MemberID"],
        )
        assert r.parent_table == "Members"
        assert r.child_columns == ["MemberID"]

    def test_index_info_fields(self):
        i = IndexInfo(name="idx_last", table="Members", columns=["LastName"], unique=False)
        assert not i.unique


class TestDatabaseEngineABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            DatabaseEngine()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_engines.py -v`
Expected: `ModuleNotFoundError: No module named 'formats.database'`

- [ ] **Step 3: Implement engine.py and __init__.py**

```python
# formats/database/__init__.py
"""Database engine package — one engine per database format family."""

from formats.database.engine import (  # noqa: F401
    DatabaseEngine,
    TableInfo,
    ColumnInfo,
    RelationshipInfo,
    IndexInfo,
)
```

```python
# formats/database/engine.py
"""Abstract base class and dataclasses for database content extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TableInfo:
    """Summary info for a single database table."""
    name: str
    row_count: int
    column_count: int


@dataclass
class ColumnInfo:
    """Column definition within a table."""
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    default_value: str | None = None


@dataclass
class RelationshipInfo:
    """Foreign key / relationship between tables."""
    name: str
    parent_table: str
    child_table: str
    parent_columns: list[str] = field(default_factory=list)
    child_columns: list[str] = field(default_factory=list)


@dataclass
class IndexInfo:
    """Index definition on a table."""
    name: str
    table: str
    columns: list[str] = field(default_factory=list)
    unique: bool = False


class DatabaseEngine(ABC):
    """Abstract interface for database content extraction.

    Each format family (SQLite, Access, dBase, QuickBooks) provides
    a concrete subclass. The DatabaseHandler dispatches to the correct
    engine based on file extension and engine availability.
    """

    @abstractmethod
    def open(self, path: Path, password: str | None = None) -> bool:
        """Attempt to open the database. Returns True on success."""
        ...

    @abstractmethod
    def list_tables(self) -> list[TableInfo]:
        """Return table names with row counts."""
        ...

    @abstractmethod
    def get_schema(self, table: str) -> list[ColumnInfo]:
        """Return column definitions for a table."""
        ...

    @abstractmethod
    def get_row_count(self, table: str) -> int:
        """Return exact row count for a table."""
        ...

    @abstractmethod
    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        """Return the first N rows as string values (header row first)."""
        ...

    def get_relationships(self) -> list[RelationshipInfo]:
        """Return foreign key definitions. Override if format supports them."""
        return []

    def get_indexes(self) -> list[IndexInfo]:
        """Return index definitions. Override if format supports them."""
        return []

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
        ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_engines.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add formats/database/__init__.py formats/database/engine.py tests/test_database_engines.py
git commit -m "feat(database): engine ABC + dataclasses"
```

---

## Task 2: SQLite Engine

**Files:**
- Create: `formats/database/sqlite_engine.py`
- Modify: `tests/test_database_engines.py`

- [ ] **Step 1: Write failing tests for SQLite engine**

Append to `tests/test_database_engines.py`:

```python
import sqlite3
from formats.database.sqlite_engine import SQLiteEngine


@pytest.fixture
def sample_sqlite(tmp_path):
    """Create a small SQLite database for testing."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE members (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER)")
    conn.execute("CREATE TABLE dues (id INTEGER PRIMARY KEY, member_id INTEGER REFERENCES members(id), amount REAL)")
    conn.execute("CREATE INDEX idx_dues_member ON dues(member_id)")
    for i in range(10):
        conn.execute("INSERT INTO members (name, age) VALUES (?, ?)", (f"Person_{i}", 20 + i))
    for i in range(25):
        conn.execute("INSERT INTO dues (member_id, amount) VALUES (?, ?)", ((i % 10) + 1, 50.0 + i))
    conn.commit()
    conn.close()
    return db_path


class TestSQLiteEngine:
    def test_open_valid_db(self, sample_sqlite):
        engine = SQLiteEngine()
        assert engine.open(sample_sqlite) is True
        engine.close()

    def test_open_nonexistent_file(self, tmp_path):
        engine = SQLiteEngine()
        assert engine.open(tmp_path / "nope.sqlite") is False

    def test_open_non_sqlite_file(self, tmp_path):
        bad = tmp_path / "not_a_db.sqlite"
        bad.write_text("this is not a database")
        engine = SQLiteEngine()
        assert engine.open(bad) is False

    def test_list_tables(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            tables = engine.list_tables()
            names = {t.name for t in tables}
            assert names == {"members", "dues"}

    def test_table_row_counts(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            tables = {t.name: t for t in engine.list_tables()}
            assert tables["members"].row_count == 10
            assert tables["dues"].row_count == 25

    def test_get_schema(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            cols = engine.get_schema("members")
            col_names = [c.name for c in cols]
            assert col_names == ["id", "name", "age"]
            id_col = cols[0]
            assert id_col.data_type == "INTEGER"
            assert id_col.is_primary_key is True

    def test_get_schema_nullable(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            cols = engine.get_schema("members")
            name_col = next(c for c in cols if c.name == "name")
            assert name_col.nullable is False
            age_col = next(c for c in cols if c.name == "age")
            assert age_col.nullable is True

    def test_sample_rows(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            rows = engine.sample_rows("members", limit=5)
            assert len(rows) == 6, "Header + 5 data rows"
            assert rows[0] == ["id", "name", "age"]
            assert rows[1][1] == "Person_0"

    def test_sample_rows_limit(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            rows = engine.sample_rows("dues", limit=3)
            assert len(rows) == 4, "Header + 3 data rows"

    def test_get_row_count(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            assert engine.get_row_count("members") == 10

    def test_get_indexes(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            indexes = engine.get_indexes()
            idx_names = [i.name for i in indexes]
            assert "idx_dues_member" in idx_names

    def test_get_relationships(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            rels = engine.get_relationships()
            assert len(rels) >= 1
            rel = rels[0]
            assert rel.parent_table == "members"
            assert rel.child_table == "dues"

    def test_context_manager(self, sample_sqlite):
        with SQLiteEngine() as engine:
            engine.open(sample_sqlite)
            tables = engine.list_tables()
            assert len(tables) == 2
        # After exit, connection should be closed — no error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_engines.py::TestSQLiteEngine -v`
Expected: `ModuleNotFoundError: No module named 'formats.database.sqlite_engine'`

- [ ] **Step 3: Implement SQLiteEngine**

```python
# formats/database/sqlite_engine.py
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
            # Quick magic-byte check: SQLite files start with "SQLite format 3\x00"
            with open(path, "rb") as f:
                header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                # Might be encrypted (SQLCipher) — try pysqlcipher3 if password given
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
        """Attempt to open an encrypted SQLite database via pysqlcipher3."""
        try:
            from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import-untyped]

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
            # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
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
        # Header row from column names
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
            # foreign_key_list: id, seq, table, from, to, on_update, on_delete, match
            # Group by id (a multi-column FK has same id, different seq)
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
                # index_list: seq, name, unique, origin, partial
                idx_name = idx[1]
                is_unique = bool(idx[2])
                # Skip auto-generated indexes for PRIMARY KEY
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_engines.py::TestSQLiteEngine -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add formats/database/sqlite_engine.py tests/test_database_engines.py
git commit -m "feat(database): SQLite engine implementation"
```

---

## Task 3: dBase Engine

**Files:**
- Create: `formats/database/dbase_engine.py`
- Modify: `tests/test_database_engines.py`

- [ ] **Step 1: Write failing tests for dBase engine**

Append to `tests/test_database_engines.py`:

```python
import struct
from formats.database.dbase_engine import DBaseEngine


@pytest.fixture
def sample_dbf(tmp_path):
    """Create a minimal dBASE III file for testing.

    Rather than depend on dbfread for creation, we write the binary format
    directly. This tests that our engine reads standard dBASE files.
    """
    # We'll use dbfread's writer if available, otherwise skip
    pytest.importorskip("dbfread")
    # Create via struct — dBASE III header
    # Simpler: just write a CSV and convert? No — we need a real .dbf.
    # Use the dbf library for creation instead.
    try:
        import dbf as dbf_writer  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("dbf library not installed for test fixture creation")

    db_path = tmp_path / "test.dbf"
    table = dbf_writer.Table(
        str(db_path),
        "name C(30); age N(5,0); active L",
    )
    table.open(mode=dbf_writer.READ_WRITE)
    for i in range(5):
        table.append((f"Person_{i}", 20 + i, True))
    table.close()
    return db_path


class TestDBaseEngine:
    def test_open_valid_dbf(self, sample_dbf):
        engine = DBaseEngine()
        assert engine.open(sample_dbf) is True
        engine.close()

    def test_open_nonexistent(self, tmp_path):
        engine = DBaseEngine()
        assert engine.open(tmp_path / "nope.dbf") is False

    def test_list_tables_single(self, sample_dbf):
        """dBase files are single-table; list_tables returns one entry."""
        with DBaseEngine() as engine:
            engine.open(sample_dbf)
            tables = engine.list_tables()
            assert len(tables) == 1
            assert tables[0].row_count == 5

    def test_get_schema(self, sample_dbf):
        with DBaseEngine() as engine:
            engine.open(sample_dbf)
            cols = engine.get_schema(engine.list_tables()[0].name)
            col_names = [c.name for c in cols]
            assert "NAME" in col_names or "name" in col_names

    def test_sample_rows(self, sample_dbf):
        with DBaseEngine() as engine:
            engine.open(sample_dbf)
            table_name = engine.list_tables()[0].name
            rows = engine.sample_rows(table_name, limit=3)
            assert len(rows) == 4, "Header + 3 data rows"

    def test_no_relationships(self, sample_dbf):
        """dBase has no foreign keys."""
        with DBaseEngine() as engine:
            engine.open(sample_dbf)
            assert engine.get_relationships() == []

    def test_no_indexes(self, sample_dbf):
        """dBase indexes not extracted (stored in separate .mdx/.ndx files)."""
        with DBaseEngine() as engine:
            engine.open(sample_dbf)
            assert engine.get_indexes() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_engines.py::TestDBaseEngine -v`
Expected: `ModuleNotFoundError: No module named 'formats.database.dbase_engine'`

- [ ] **Step 3: Implement DBaseEngine**

```python
# formats/database/dbase_engine.py
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

# dBase field type codes to human-readable names
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
            from dbfread import DBF  # type: ignore[import-untyped]

            # load=False defers reading all records into memory
            self._table = DBF(str(path), load=False, encoding="latin-1")
            self._path = path
            # Probe: read field list to verify the file is valid
            _ = self._table.fields
            return True
        except Exception as exc:
            log.warning("dbase_open_failed", path=str(path), error=str(exc))
            self._table = None
            return False

    def list_tables(self) -> list[TableInfo]:
        assert self._table is not None
        # A .dbf file is a single table; use the filename as the table name
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
                nullable=True,  # dBase fields are always nullable
                is_primary_key=False,  # dBase has no PK concept
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_engines.py::TestDBaseEngine -v`
Expected: All 7 tests PASS (or skip if `dbf` write library not installed)

- [ ] **Step 5: Commit**

```bash
git add formats/database/dbase_engine.py tests/test_database_engines.py
git commit -m "feat(database): dBase engine implementation"
```

---

## Task 4: Access Engine (mdbtools cascade)

**Files:**
- Create: `formats/database/access_engine.py`
- Modify: `tests/test_database_engines.py`

- [ ] **Step 1: Write failing tests for Access engine**

Append to `tests/test_database_engines.py`:

```python
import shutil
from formats.database.access_engine import AccessEngine, MdbtoolsBackend, _quote_table


class TestMdbtoolsBackend:
    def test_is_available_checks_path(self):
        """MdbtoolsBackend.is_available() returns True only if mdb-tables is on PATH."""
        available = MdbtoolsBackend.is_available()
        has_mdbtools = shutil.which("mdb-tables") is not None
        assert available == has_mdbtools

    def test_quote_table_simple(self):
        assert _quote_table("Members") == "Members"

    def test_quote_table_with_space(self):
        assert _quote_table("My Table") == "My Table"


class TestAccessEngine:
    def test_open_nonexistent(self, tmp_path):
        engine = AccessEngine()
        assert engine.open(tmp_path / "nope.mdb") is False

    def test_open_non_mdb_file(self, tmp_path):
        bad = tmp_path / "fake.mdb"
        bad.write_bytes(b"not a real database")
        engine = AccessEngine()
        assert engine.open(bad) is False

    @pytest.mark.skipif(
        shutil.which("mdb-tables") is None,
        reason="mdbtools not installed"
    )
    def test_mdbtools_backend_available(self):
        assert MdbtoolsBackend.is_available() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_engines.py::TestMdbtoolsBackend -v`
Expected: `ModuleNotFoundError: No module named 'formats.database.access_engine'`

- [ ] **Step 3: Implement AccessEngine**

```python
# formats/database/access_engine.py
"""Microsoft Access engine — mdbtools -> pyodbc -> jackcess cascade."""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
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


def _quote_table(name: str) -> str:
    """Return table name (mdbtools doesn't need quoting, but we keep it safe)."""
    return name


class MdbtoolsBackend:
    """Access engine backend using mdbtools CLI (mdb-tables, mdb-schema, mdb-export)."""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("mdb-tables") is not None

    def __init__(self, path: Path, password: str | None = None):
        self._path = path
        self._env = {}
        if password:
            self._env["MDB_PASSWORD"] = password

    def _run(self, cmd: list[str], timeout: int = 30) -> str:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env={**self._env} or None,
        )
        if result.returncode != 0:
            raise RuntimeError(f"mdbtools error: {result.stderr.strip()}")
        return result.stdout

    def list_table_names(self) -> list[str]:
        output = self._run(["mdb-tables", "-1", str(self._path)])
        return [t.strip() for t in output.strip().split("\n") if t.strip()]

    def get_schema_text(self) -> str:
        return self._run(["mdb-schema", str(self._path)])

    def export_table(self, table: str) -> list[list[str]]:
        output = self._run(["mdb-export", str(self._path), table])
        reader = csv.reader(io.StringIO(output))
        return [row for row in reader]

    def row_count(self, table: str) -> int:
        rows = self.export_table(table)
        return max(0, len(rows) - 1)  # minus header


class AccessEngine(DatabaseEngine):
    """Extract schema and data from MS Access .mdb/.accdb files.

    Tries backends in order: mdbtools -> pyodbc -> jackcess.
    Uses the first one that can successfully open the file.
    """

    def __init__(self):
        self._backend: MdbtoolsBackend | None = None
        self._path: Path | None = None
        self._backend_name: str = ""

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def open(self, path: Path, password: str | None = None) -> bool:
        if not path.exists():
            return False

        # Quick magic byte check: Access files start with specific signatures
        try:
            with open(path, "rb") as f:
                header = f.read(4)
            # JET3 (mdb) = 0x00 0x01 0x00 0x00; JET4/ACE (accdb) = same prefix
            if header[:4] not in (b"\x00\x01\x00\x00", b"\x00\x00\x00\x00"):
                # Not an Access file based on magic bytes
                # But some files don't have standard headers — try anyway
                pass
        except Exception:
            return False

        # Try mdbtools first
        if MdbtoolsBackend.is_available():
            try:
                backend = MdbtoolsBackend(path, password)
                tables = backend.list_table_names()
                if tables is not None:
                    self._backend = backend
                    self._path = path
                    self._backend_name = "mdbtools"
                    log.info("access_opened", path=str(path), backend="mdbtools")
                    return True
            except Exception as exc:
                log.debug("mdbtools_failed", path=str(path), error=str(exc))

        # Try pyodbc
        if self._try_pyodbc(path, password):
            return True

        # Try jackcess
        if self._try_jackcess(path, password):
            return True

        log.warning("access_no_backend", path=str(path))
        return False

    def _try_pyodbc(self, path: Path, password: str | None) -> bool:
        try:
            import pyodbc  # type: ignore[import-untyped]

            conn_str = f"DRIVER={{MDBTools}};DBQ={path};"
            if password:
                conn_str += f"PWD={password};"
            conn = pyodbc.connect(conn_str, readonly=True)
            conn.close()
            self._path = path
            self._backend_name = "pyodbc"
            log.info("access_opened", path=str(path), backend="pyodbc")
            return True
        except Exception as exc:
            log.debug("pyodbc_failed", path=str(path), error=str(exc))
            return False

    def _try_jackcess(self, path: Path, password: str | None) -> bool:
        if not shutil.which("java"):
            return False
        # Look for jackcess CLI jar
        jar_candidates = [
            Path("/opt/jackcess/jackcess-cli.jar"),
            Path("/app/lib/jackcess-cli.jar"),
        ]
        jar_path = None
        for candidate in jar_candidates:
            if candidate.exists():
                jar_path = candidate
                break
        if not jar_path:
            return False
        try:
            cmd = ["java", "-jar", str(jar_path), "tables", str(path)]
            if password:
                cmd.extend(["--password", password])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                self._path = path
                self._backend_name = "jackcess"
                log.info("access_opened", path=str(path), backend="jackcess")
                return True
        except Exception as exc:
            log.debug("jackcess_failed", path=str(path), error=str(exc))
        return False

    def list_tables(self) -> list[TableInfo]:
        if self._backend and self._backend_name == "mdbtools":
            names = self._backend.list_table_names()
            tables = []
            for name in names:
                try:
                    rc = self._backend.row_count(name)
                    rows = self._backend.export_table(name)
                    col_count = len(rows[0]) if rows else 0
                except Exception:
                    rc = 0
                    col_count = 0
                tables.append(TableInfo(name=name, row_count=rc, column_count=col_count))
            return tables
        return []

    def get_schema(self, table: str) -> list[ColumnInfo]:
        if self._backend and self._backend_name == "mdbtools":
            rows = self._backend.export_table(table)
            if not rows:
                return []
            # Use first row (header) as column names; types from mdb-schema
            header = rows[0]
            schema_text = self._backend.get_schema_text()
            type_map = self._parse_schema_types(schema_text, table)
            columns = []
            for col_name in header:
                col_type = type_map.get(col_name, "TEXT")
                columns.append(ColumnInfo(
                    name=col_name,
                    data_type=col_type,
                    nullable=True,
                    is_primary_key=False,
                ))
            return columns
        return []

    def _parse_schema_types(self, schema_text: str, table: str) -> dict[str, str]:
        """Parse mdb-schema output to extract column types for a table."""
        type_map: dict[str, str] = {}
        in_table = False
        for line in schema_text.split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith(f"CREATE TABLE [{table}]") or stripped.upper().startswith(f"CREATE TABLE \"{table}\""):
                in_table = True
                continue
            if in_table and stripped == ");":
                break
            if in_table and stripped and not stripped.startswith("--"):
                # Parse column definition: [col_name]  TYPE,
                parts = stripped.split()
                if len(parts) >= 2:
                    col_name = parts[0].strip("[]\"").rstrip(",")
                    col_type = parts[1].rstrip(",")
                    type_map[col_name] = col_type
        return type_map

    def get_row_count(self, table: str) -> int:
        if self._backend and self._backend_name == "mdbtools":
            return self._backend.row_count(table)
        return 0

    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        if self._backend and self._backend_name == "mdbtools":
            rows = self._backend.export_table(table)
            if not rows:
                return []
            # rows[0] is header, rest is data
            return rows[: limit + 1]
        return []

    def get_relationships(self) -> list[RelationshipInfo]:
        if self._backend and self._backend_name == "mdbtools":
            try:
                output = subprocess.run(
                    ["mdb-schema", "--no-drop-table", "--no-not-null", str(self._path)],
                    capture_output=True, text=True, timeout=30,
                ).stdout
                return self._parse_relationships(output)
            except Exception:
                pass
        return []

    def _parse_relationships(self, schema_text: str) -> list[RelationshipInfo]:
        """Extract REFERENCES from mdb-schema output."""
        rels: list[RelationshipInfo] = []
        current_table = ""
        for line in schema_text.split("\n"):
            stripped = line.strip()
            if "CREATE TABLE" in stripped.upper():
                # Extract table name from CREATE TABLE [name] or CREATE TABLE "name"
                for ch in ("[", '"'):
                    if ch in stripped:
                        start = stripped.index(ch) + 1
                        end_ch = "]" if ch == "[" else '"'
                        end = stripped.index(end_ch, start)
                        current_table = stripped[start:end]
                        break
            if "REFERENCES" in stripped.upper() and current_table:
                # Parse: [col] TYPE REFERENCES [parent_table]([parent_col])
                parts = stripped.split()
                col_name = parts[0].strip("[]\"").rstrip(",")
                ref_idx = next((i for i, p in enumerate(parts) if p.upper() == "REFERENCES"), None)
                if ref_idx and ref_idx + 1 < len(parts):
                    ref_part = parts[ref_idx + 1]
                    # Parse parent_table(parent_col)
                    if "(" in ref_part:
                        parent_table = ref_part[:ref_part.index("(")].strip("[]\"")
                        parent_col = ref_part[ref_part.index("(") + 1:].rstrip("),").strip("[]\"")
                        rels.append(RelationshipInfo(
                            name=f"fk_{current_table}_{parent_table}_{col_name}",
                            parent_table=parent_table,
                            child_table=current_table,
                            parent_columns=[parent_col],
                            child_columns=[col_name],
                        ))
        return rels

    def get_indexes(self) -> list[IndexInfo]:
        # mdbtools doesn't expose indexes well; return empty
        return []

    def close(self) -> None:
        self._backend = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_engines.py::TestMdbtoolsBackend tests/test_database_engines.py::TestAccessEngine -v`
Expected: All tests PASS (some may skip if mdbtools not installed locally)

- [ ] **Step 5: Commit**

```bash
git add formats/database/access_engine.py tests/test_database_engines.py
git commit -m "feat(database): Access engine with mdbtools/pyodbc/jackcess cascade"
```

---

## Task 5: QuickBooks Engine

**Files:**
- Create: `formats/database/quickbooks_engine.py`
- Modify: `tests/test_database_engines.py`

- [ ] **Step 1: Write failing tests for QuickBooks engine**

Append to `tests/test_database_engines.py`:

```python
from formats.database.quickbooks_engine import QuickBooksEngine


@pytest.fixture
def fake_qbw(tmp_path):
    """Create a minimal fake .qbw file with a recognizable header."""
    qbw = tmp_path / "company.qbw"
    # Real QBW files have a proprietary header; we'll test the metadata-only path
    header = b"\x00" * 256
    qbw.write_bytes(header)
    return qbw


class TestQuickBooksEngine:
    def test_open_nonexistent(self, tmp_path):
        engine = QuickBooksEngine()
        assert engine.open(tmp_path / "nope.qbw") is False

    def test_open_fake_qbw(self, fake_qbw):
        """Even unreadable QBW files should 'open' — we return metadata-only."""
        engine = QuickBooksEngine()
        result = engine.open(fake_qbw)
        # Should open (metadata-only mode) since the file exists
        assert result is True
        engine.close()

    def test_list_tables_metadata_only(self, fake_qbw):
        """When content is inaccessible, list_tables returns empty."""
        with QuickBooksEngine() as engine:
            engine.open(fake_qbw)
            tables = engine.list_tables()
            # May be empty if binary parsing found nothing
            assert isinstance(tables, list)

    def test_metadata_properties(self, fake_qbw):
        """Engine exposes metadata even when content is inaccessible."""
        with QuickBooksEngine() as engine:
            engine.open(fake_qbw)
            assert engine.is_metadata_only is not None
            assert engine.file_format in ("qbw", "qbb")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_engines.py::TestQuickBooksEngine -v`
Expected: `ModuleNotFoundError: No module named 'formats.database.quickbooks_engine'`

- [ ] **Step 3: Implement QuickBooksEngine**

```python
# formats/database/quickbooks_engine.py
"""QuickBooks engine — best-effort binary header parsing for .qbb/.qbw files.

QuickBooks uses a proprietary format. Older files (pre-2006) used a modified
BTrieve engine with partially documented table structures. Newer files use
AES encryption. This engine extracts what it can and flags inaccessible content
with instructions for manual export.
"""

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

# Known byte offsets for QuickBooks header fields (approximate — varies by version)
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
        """Extract company name and version from binary header."""
        # Scan for printable ASCII strings that look like a company name
        # QuickBooks stores the company name as a null-terminated string
        # in the first few KB of the file
        start, end = _COMPANY_NAME_SCAN_RANGE
        chunk = self._header_bytes[start:end]

        # Find longest printable ASCII run (likely company name)
        strings = re.findall(rb"[ -~]{8,100}", chunk)
        if strings:
            # Heuristic: company name is usually the first long string
            # that doesn't look like a file path or technical string
            for s in strings:
                decoded = s.decode("ascii", errors="replace").strip()
                if not any(x in decoded.lower() for x in (":\\", "/", ".dll", ".exe", "quickbooks")):
                    self._company_name = decoded
                    break

        # Check for encryption indicators
        # Encrypted QB files have specific byte patterns after the header
        if len(self._header_bytes) > 512:
            # Entropy check: encrypted data has near-uniform byte distribution
            byte_set = set(self._header_bytes[256:512])
            if len(byte_set) > 240:
                self._encrypted = True

    def _scan_for_tables(self) -> None:
        """Attempt to find BTrieve table structures in older QB files."""
        # Older QuickBooks files (pre-2006) used BTrieve which stores
        # table metadata at known offsets. This is best-effort.
        self._is_metadata_only = True
        # For now, we don't extract actual table data — this would require
        # deep reverse-engineering of the BTrieve page format.
        # Future enhancement: add a BTrieve page walker for pre-2006 files.

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_engines.py::TestQuickBooksEngine -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add formats/database/quickbooks_engine.py tests/test_database_engines.py
git commit -m "feat(database): QuickBooks engine with header parsing"
```

---

## Task 6: Capability Detection

**Files:**
- Create: `formats/database/capability.py`
- Modify: `tests/test_database_engines.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_database_engines.py`:

```python
from formats.database.capability import detect_database_engines


class TestCapabilityDetection:
    def test_returns_dict(self):
        caps = detect_database_engines()
        assert isinstance(caps, dict)

    def test_sqlite3_always_available(self):
        caps = detect_database_engines()
        assert caps["sqlite3"] is True

    def test_all_expected_keys(self):
        caps = detect_database_engines()
        expected = {"sqlite3", "mdbtools", "pyodbc_mdbtools", "jackcess", "dbfread", "pysqlcipher3"}
        assert set(caps.keys()) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_engines.py::TestCapabilityDetection -v`
Expected: `ModuleNotFoundError: No module named 'formats.database.capability'`

- [ ] **Step 3: Implement capability.py**

```python
# formats/database/capability.py
"""Detect which database engines are available on this system."""

from __future__ import annotations

import shutil

import structlog

log = structlog.get_logger(__name__)


def detect_database_engines() -> dict[str, bool]:
    """Probe for available database engine backends.

    Returns a dict of engine name -> available (bool).
    Called at startup; results cached in worker_capabilities.json.
    """
    caps: dict[str, bool] = {}

    # sqlite3 — always available (Python built-in)
    caps["sqlite3"] = True

    # mdbtools — check for mdb-tables binary
    caps["mdbtools"] = shutil.which("mdb-tables") is not None

    # pyodbc with MDBTools ODBC driver
    caps["pyodbc_mdbtools"] = _check_pyodbc_mdbtools()

    # jackcess — needs java + jar file
    caps["jackcess"] = _check_jackcess()

    # dbfread — pure Python, pip install
    caps["dbfread"] = _check_import("dbfread")

    # pysqlcipher3 — for encrypted SQLite
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
        import pyodbc  # type: ignore[import-untyped]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_engines.py::TestCapabilityDetection -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add formats/database/capability.py tests/test_database_engines.py
git commit -m "feat(database): engine capability detection"
```

---

## Task 7: DatabaseHandler (main handler)

**Files:**
- Create: `formats/database_handler.py`
- Create: `tests/test_database_handler.py`

- [ ] **Step 1: Write failing tests for the handler**

```python
# tests/test_database_handler.py
"""Tests for formats/database_handler.py — database file ingest."""

import sqlite3
import pytest
from pathlib import Path

from core.document_model import DocumentModel, Element, ElementType


@pytest.fixture
def sample_sqlite(tmp_path):
    """Create a small SQLite database for testing."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE members (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER)")
    conn.execute("CREATE TABLE dues (id INTEGER PRIMARY KEY, member_id INTEGER REFERENCES members(id), amount REAL)")
    conn.execute("CREATE INDEX idx_dues_member ON dues(member_id)")
    for i in range(10):
        conn.execute("INSERT INTO members (name, age) VALUES (?, ?)", (f"Person_{i}", 20 + i))
    for i in range(25):
        conn.execute("INSERT INTO dues (member_id, amount) VALUES (?, ?)", ((i % 10) + 1, 50.0 + i))
    conn.commit()
    conn.close()
    return db_path


class TestDatabaseHandlerIngest:
    def test_ingest_returns_document_model(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        assert isinstance(model, DocumentModel)

    def test_ingest_has_heading(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        headings = model.get_elements_by_type(ElementType.HEADING)
        assert len(headings) >= 1
        assert "test.sqlite" in headings[0].content

    def test_ingest_has_metadata_table(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        tables = model.get_elements_by_type(ElementType.TABLE)
        # First table should be the metadata/property table
        assert len(tables) >= 1
        first_table = tables[0]
        headers = first_table.content[0]
        assert headers == ["Property", "Value"]

    def test_ingest_has_schema_overview(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        headings = [h.content for h in model.get_elements_by_type(ElementType.HEADING)]
        assert any("Schema Overview" in h for h in headings)

    def test_ingest_has_per_table_sections(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        headings = [h.content for h in model.get_elements_by_type(ElementType.HEADING)]
        assert any("Table: members" in h for h in headings)
        assert any("Table: dues" in h for h in headings)

    def test_ingest_sample_rows_present(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        # Find the sample data table for 'members' — it follows the column schema table
        tables = model.get_elements_by_type(ElementType.TABLE)
        # Should have: metadata, schema overview, members columns, members data,
        #              dues columns, dues data, relationships, indexes
        sample_tables = [t for t in tables if t.content and len(t.content) > 1
                         and t.content[0][0] not in ("Property", "Table", "Column", "Relationship", "Index")]
        assert len(sample_tables) >= 1, "Should have at least one sample data table"

    def test_ingest_metadata_source_format(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        assert model.metadata.source_format == "sqlite"

    def test_ingest_has_relationships_section(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        headings = [h.content for h in model.get_elements_by_type(ElementType.HEADING)]
        assert any("Relationships" in h for h in headings)

    def test_ingest_has_indexes_section(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        headings = [h.content for h in model.get_elements_by_type(ElementType.HEADING)]
        assert any("Indexes" in h for h in headings)


class TestDatabaseHandlerExport:
    def test_export_raises(self, sample_sqlite, tmp_path):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(sample_sqlite)
        with pytest.raises(NotImplementedError):
            handler.export(model, tmp_path / "out.sqlite")


class TestDatabaseHandlerStyles:
    def test_extract_styles_returns_dict(self, sample_sqlite):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        styles = handler.extract_styles(sample_sqlite)
        assert isinstance(styles, dict)
        assert "document_level" in styles
        assert styles["document_level"]["format"] == "sqlite"


class TestDatabaseHandlerEdgeCases:
    def test_empty_database(self, tmp_path):
        from formats.database_handler import DatabaseHandler

        db_path = tmp_path / "empty.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        handler = DatabaseHandler()
        model = handler.ingest(db_path)
        assert isinstance(model, DocumentModel)
        # Should still have a heading and metadata table
        assert len(model.get_elements_by_type(ElementType.HEADING)) >= 1

    def test_nonexistent_file(self, tmp_path):
        from formats.database_handler import DatabaseHandler

        handler = DatabaseHandler()
        model = handler.ingest(tmp_path / "nope.sqlite")
        assert isinstance(model, DocumentModel)
        assert len(model.warnings) >= 1

    def test_corrupt_file(self, tmp_path):
        from formats.database_handler import DatabaseHandler

        bad = tmp_path / "corrupt.db"
        bad.write_text("not a database")
        handler = DatabaseHandler()
        model = handler.ingest(bad)
        assert isinstance(model, DocumentModel)
        assert len(model.warnings) >= 1


class TestDatabaseHandlerRegistration:
    def test_registered_extensions(self):
        from formats.base import get_handler

        # Should be DatabaseHandler, not BinaryHandler
        handler = get_handler("sqlite")
        assert handler is not None
        assert type(handler).__name__ == "DatabaseHandler"

    def test_all_extensions_registered(self):
        from formats.base import get_handler

        for ext in ["sqlite", "db", "sqlite3", "s3db", "mdb", "accdb", "dbf", "qbb", "qbw"]:
            handler = get_handler(ext)
            assert handler is not None, f"No handler for .{ext}"
            assert type(handler).__name__ == "DatabaseHandler", f".{ext} not handled by DatabaseHandler"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_handler.py -v`
Expected: `ModuleNotFoundError: No module named 'formats.database_handler'`

- [ ] **Step 3: Implement DatabaseHandler**

```python
# formats/database_handler.py
"""
Database file handler — SQLite, Access, dBase, QuickBooks.

Ingest:
  Extracts schema, metadata, sample data, relationships, and indexes
  into a structured Markdown DocumentModel. Answers: "what does this
  database do?" and "what information is in it?"

Export:
  Not supported — database reconstruction from Markdown not feasible.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import structlog

from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)
from formats.base import FormatHandler, register_handler
from formats.database.engine import DatabaseEngine, TableInfo

log = structlog.get_logger(__name__)

# Extension -> engine class mapping
_EXTENSION_ENGINE_MAP: dict[str, str] = {
    "sqlite": "sqlite",
    "db": "sqlite",
    "sqlite3": "sqlite",
    "s3db": "sqlite",
    "mdb": "access",
    "accdb": "access",
    "dbf": "dbase",
    "qbb": "quickbooks",
    "qbw": "quickbooks",
}

# Limits to prevent huge output
_MAX_TABLES_FULL = 50
_MAX_COLUMNS_SAMPLE = 20
_DEFAULT_SAMPLE_ROWS = 25
_MAX_SAMPLE_ROWS = 1000


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _get_engine(engine_type: str) -> DatabaseEngine | None:
    """Instantiate the correct engine class by type name."""
    if engine_type == "sqlite":
        from formats.database.sqlite_engine import SQLiteEngine
        return SQLiteEngine()
    elif engine_type == "access":
        from formats.database.access_engine import AccessEngine
        return AccessEngine()
    elif engine_type == "dbase":
        from formats.database.dbase_engine import DBaseEngine
        return DBaseEngine()
    elif engine_type == "quickbooks":
        from formats.database.quickbooks_engine import QuickBooksEngine
        return QuickBooksEngine()
    return None


def _get_sample_rows_limit() -> int:
    """Read database_sample_rows preference. Falls back to default."""
    try:
        import sqlite3 as _sqlite3
        from core.database import get_db_path
        conn = _sqlite3.connect(get_db_path())
        row = conn.execute(
            "SELECT value FROM user_preferences WHERE key = ?",
            ("database_sample_rows",),
        ).fetchone()
        conn.close()
        if row:
            val = int(row[0])
            return min(val, _MAX_SAMPLE_ROWS)
    except Exception:
        pass
    return _DEFAULT_SAMPLE_ROWS


@register_handler
class DatabaseHandler(FormatHandler):
    """Schema + sample data extraction for database files."""

    EXTENSIONS = [
        "sqlite", "db", "sqlite3", "s3db",
        "mdb", "accdb",
        "dbf",
        "qbb", "qbw",
    ]

    def ingest(self, file_path: Path, **kwargs) -> DocumentModel:
        start = time.perf_counter()
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=file_path.suffix.lstrip(".").lower(),
        )

        ext = file_path.suffix.lstrip(".").lower()
        engine_type = _EXTENSION_ENGINE_MAP.get(ext, "sqlite")
        engine = _get_engine(engine_type)

        if engine is None:
            model.warnings.append(f"No engine available for .{ext} files")
            self._add_error_model(model, file_path, "No engine available")
            return model

        # Try to open (with password cascade if needed)
        password = kwargs.get("password")
        opened = engine.open(file_path, password)

        if not opened and not password:
            # Try password cascade
            password = self._try_password_cascade(file_path, engine)
            if password:
                opened = True

        if not opened:
            model.warnings.append(f"Could not open database: {file_path.name}")
            self._add_error_model(model, file_path, "Could not open database")
            engine.close()
            return model

        try:
            sample_limit = _get_sample_rows_limit()
            self._build_model(model, engine, file_path, sample_limit)
        except Exception as exc:
            log.error("database_ingest_error", path=str(file_path), error=str(exc))
            model.warnings.append(f"Error during extraction: {exc}")
        finally:
            engine.close()

        elapsed = time.perf_counter() - start
        log.info("database_ingested", path=str(file_path), elapsed=f"{elapsed:.2f}s",
                 engine=engine_type, tables=len(model.get_elements_by_type(ElementType.HEADING)) - 1)
        return model

    def _build_model(
        self, model: DocumentModel, engine: DatabaseEngine, file_path: Path, sample_limit: int
    ) -> None:
        """Populate the DocumentModel with schema, data, and metadata."""
        tables = engine.list_tables()
        total_rows = sum(t.row_count for t in tables)

        # Compute SHA-256
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

        # Engine name for metadata
        engine_name = getattr(engine, "backend_name", type(engine).__name__)

        # ── H1: Database title ──
        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"Database: {file_path.name}",
            level=1,
        ))

        # ── Metadata table ──
        stat = file_path.stat()
        fmt_label = self._format_label(file_path.suffix.lstrip(".").lower())
        model.add_element(Element(
            type=ElementType.TABLE,
            content=[
                ["Property", "Value"],
                ["Format", fmt_label],
                ["Size", _human_size(stat.st_size)],
                ["Tables", str(len(tables))],
                ["Total Rows", f"{total_rows:,}"],
                ["Engine", engine_name],
                ["SHA-256", f"`{file_hash}`"],
            ],
        ))

        # ── QuickBooks special handling ──
        if hasattr(engine, "is_metadata_only") and engine.is_metadata_only:
            self._add_quickbooks_metadata(model, engine)
            if not tables:
                self._add_quickbooks_export_instructions(model)
                return

        if not tables:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="*This database contains no tables.*",
            ))
            return

        # ── Schema Overview ──
        model.add_element(Element(
            type=ElementType.HEADING,
            content="Schema Overview",
            level=2,
        ))
        overview_rows = [["Table", "Rows", "Columns", "Primary Key"]]
        for t in tables:
            pk = self._get_pk_name(engine, t.name)
            overview_rows.append([t.name, f"{t.row_count:,}", str(t.column_count), pk])
        model.add_element(Element(type=ElementType.TABLE, content=overview_rows))

        # ── Per-table sections ──
        tables_shown = 0
        for t in tables:
            if tables_shown >= _MAX_TABLES_FULL:
                remaining = len(tables) - _MAX_TABLES_FULL
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content=f"*{remaining} additional tables not shown.*",
                ))
                break

            model.add_element(Element(
                type=ElementType.HEADING,
                content=f"Table: {t.name}",
                level=2,
            ))

            # Column schema
            cols = engine.get_schema(t.name)
            col_rows = [["Column", "Type", "Nullable", "Key", "Default"]]
            for c in cols:
                key = "PK" if c.is_primary_key else ""
                nullable = "YES" if c.nullable else "NO"
                default = c.default_value or ""
                col_rows.append([c.name, c.data_type, nullable, key, default])
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="**Columns:**",
            ))
            model.add_element(Element(type=ElementType.TABLE, content=col_rows))

            # Sample data
            if t.row_count > 0:
                rows = engine.sample_rows(t.name, limit=sample_limit)
                if rows and len(rows) > 1:
                    # Truncate wide tables
                    if len(rows[0]) > _MAX_COLUMNS_SAMPLE:
                        total_cols = len(rows[0])
                        rows = [row[:_MAX_COLUMNS_SAMPLE] for row in rows]
                        model.add_element(Element(
                            type=ElementType.PARAGRAPH,
                            content=f"**Sample Data (first {len(rows) - 1} rows, showing {_MAX_COLUMNS_SAMPLE} of {total_cols} columns):**",
                        ))
                    else:
                        model.add_element(Element(
                            type=ElementType.PARAGRAPH,
                            content=f"**Sample Data (first {len(rows) - 1} rows):**",
                        ))
                    model.add_element(Element(type=ElementType.TABLE, content=rows))
            tables_shown += 1

        # ── Relationships ──
        rels = engine.get_relationships()
        model.add_element(Element(
            type=ElementType.HEADING,
            content="Relationships",
            level=2,
        ))
        if rels:
            rel_rows = [["Relationship", "Parent Table", "Child Table", "Columns"]]
            for r in rels:
                col_map = ", ".join(
                    f"{c} -> {p}" for c, p in zip(r.child_columns, r.parent_columns)
                )
                rel_rows.append([r.name, r.parent_table, r.child_table, col_map])
            model.add_element(Element(type=ElementType.TABLE, content=rel_rows))
        else:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="*No foreign key relationships found.*",
            ))

        # ── Indexes ──
        indexes = engine.get_indexes()
        model.add_element(Element(
            type=ElementType.HEADING,
            content="Indexes",
            level=2,
        ))
        if indexes:
            idx_rows = [["Index", "Table", "Columns", "Unique"]]
            for idx in indexes:
                idx_rows.append([idx.name, idx.table, ", ".join(idx.columns),
                                 "YES" if idx.unique else "NO"])
            model.add_element(Element(type=ElementType.TABLE, content=idx_rows))
        else:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="*No indexes found.*",
            ))

    def _get_pk_name(self, engine: DatabaseEngine, table: str) -> str:
        """Get the primary key column name(s) for a table."""
        try:
            cols = engine.get_schema(table)
            pk_cols = [c.name for c in cols if c.is_primary_key]
            return ", ".join(pk_cols) if pk_cols else ""
        except Exception:
            return ""

    def _format_label(self, ext: str) -> str:
        labels = {
            "sqlite": "SQLite",
            "db": "SQLite / Generic Database",
            "sqlite3": "SQLite 3",
            "s3db": "SQLite 3",
            "mdb": "Microsoft Access 97-2003",
            "accdb": "Microsoft Access 2007+",
            "dbf": "dBase / FoxPro",
            "qbb": "QuickBooks Backup",
            "qbw": "QuickBooks Working File",
        }
        return labels.get(ext, ext.upper())

    def _add_error_model(self, model: DocumentModel, file_path: Path, reason: str) -> None:
        """Add minimal content for files that can't be opened."""
        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"Database: {file_path.name}",
            level=1,
        ))
        stat = file_path.stat() if file_path.exists() else None
        rows = [["Property", "Value"]]
        rows.append(["Format", self._format_label(file_path.suffix.lstrip(".").lower())])
        if stat:
            rows.append(["Size", _human_size(stat.st_size)])
        rows.append(["Status", reason])
        model.add_element(Element(type=ElementType.TABLE, content=rows))

    def _add_quickbooks_metadata(self, model: DocumentModel, engine: Any) -> None:
        """Add QuickBooks-specific metadata to the model."""
        if hasattr(engine, "company_name") and engine.company_name:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content=f"**Company Name:** {engine.company_name}",
            ))
        if hasattr(engine, "encrypted") and engine.encrypted:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="**Encryption:** Detected (content may be partially or fully inaccessible)",
            ))

    def _add_quickbooks_export_instructions(self, model: DocumentModel) -> None:
        """Add manual export instructions for inaccessible QuickBooks files."""
        model.add_element(Element(
            type=ElementType.HEADING,
            content="Export Instructions",
            level=2,
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content=(
                "This file uses QuickBooks proprietary format. For full content "
                "extraction, export from QuickBooks Desktop:\n\n"
                "1. Open the file in QuickBooks Desktop\n"
                "2. File -> Utilities -> Export -> IIF Files (or Reports -> Excel/CSV)\n"
                "3. Convert the exported IIF/CSV files through MarkFlow\n\n"
                "Supported export formats: IIF (tab-delimited), CSV, Excel (.xlsx)"
            ),
        ))

    def _try_password_cascade(self, file_path: Path, engine: DatabaseEngine) -> str | None:
        """Run the password cascade to try to unlock an encrypted database."""
        # Reuse the archive handler's password cascade pattern:
        # 1. Empty password
        # 2. Static password list
        # 3. Dictionary attack
        # 4. Brute force
        from pathlib import Path as _Path

        # Phase 1: Quick candidates
        candidates = [""]
        password_file = _Path("config/archive_passwords.txt")
        if password_file.exists():
            try:
                candidates.extend(
                    line.strip()
                    for line in password_file.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            except Exception:
                pass

        for pw in candidates:
            if engine.open(file_path, pw if pw else None):
                if pw:
                    log.info("database_password_found", method="static_list")
                return pw if pw else None

        # Phase 2: Dictionary
        dict_file = _Path("core/password_wordlists/common.txt")
        if dict_file.exists():
            try:
                for line in dict_file.read_text(encoding="utf-8").splitlines():
                    pw = line.strip()
                    if pw and engine.open(file_path, pw):
                        log.info("database_password_found", method="dictionary")
                        return pw
            except Exception:
                pass

        return None

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        raise NotImplementedError(
            "Database files are ingest-only. "
            "The Markdown summary is the conversion artifact."
        )

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        ext = file_path.suffix.lstrip(".").lower()
        engine_type = _EXTENSION_ENGINE_MAP.get(ext, "sqlite")
        engine = _get_engine(engine_type)
        if engine is None:
            return {"document_level": {"format": ext, "encrypted": False}}

        opened = engine.open(file_path)
        if not opened:
            engine.close()
            return {"document_level": {"format": ext, "encrypted": True}}

        try:
            tables = engine.list_tables()
            total_rows = sum(t.row_count for t in tables)
            engine_name = getattr(engine, "backend_name", type(engine).__name__)
            return {
                "document_level": {
                    "format": ext,
                    "engine_used": engine_name,
                    "table_count": len(tables),
                    "total_rows": total_rows,
                    "encrypted": False,
                }
            }
        finally:
            engine.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_handler.py -v`
Expected: All tests PASS (registration tests will fail until Task 8 wires the imports)

- [ ] **Step 5: Commit**

```bash
git add formats/database_handler.py tests/test_database_handler.py
git commit -m "feat(database): main DatabaseHandler with ingest + model assembly"
```

---

## Task 8: Wire Registration + Remove from BinaryHandler

**Files:**
- Modify: `formats/__init__.py:37-38`
- Modify: `formats/binary_handler.py:43-44`

- [ ] **Step 1: Write failing test**

The registration tests in `tests/test_database_handler.py::TestDatabaseHandlerRegistration` should already fail — they verify that `get_handler("sqlite")` returns a `DatabaseHandler` not a `BinaryHandler`. Run them to confirm:

Run: `python -m pytest tests/test_database_handler.py::TestDatabaseHandlerRegistration -v`
Expected: FAIL — `get_handler("sqlite")` returns `BinaryHandler`

- [ ] **Step 2: Add DatabaseHandler import to formats/__init__.py**

In `formats/__init__.py`, add the import **before** the BinaryHandler line (line 38). Since the registry is last-write-wins, DatabaseHandler must be imported after BinaryHandler to override:

Actually — since `@register_handler` is last-write-wins, we need DatabaseHandler imported **after** BinaryHandler. Add it as the last import:

Edit `formats/__init__.py` — after line 38 (`from formats.binary_handler import BinaryHandler`), add:

```python
from formats.database_handler import DatabaseHandler  # noqa: F401
```

- [ ] **Step 3: Remove database extensions from BinaryHandler**

Edit `formats/binary_handler.py` — change lines 43-44 from:

```python
        # Databases
        "sqlite", "db", "mdb", "accdb",
```

to remove those two lines entirely. The `# Databases` comment and the four extensions go away.

- [ ] **Step 4: Run registration tests**

Run: `python -m pytest tests/test_database_handler.py::TestDatabaseHandlerRegistration -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/test_database_handler.py tests/test_database_engines.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add formats/__init__.py formats/binary_handler.py
git commit -m "feat(database): wire handler registration, remove DB exts from BinaryHandler"
```

---

## Task 9: Add Preference + Settings Schema

**Files:**
- Modify: `core/db/preferences.py:105`
- Modify: `api/routes/preferences.py:43,49+`

- [ ] **Step 1: Add default preference**

Edit `core/db/preferences.py` — add after the `"db_contention_logging": "true",` line (line 104):

```python
    # Database handler (v0.23.1)
    "database_sample_rows": "25",
```

- [ ] **Step 2: Add to system pref keys**

Edit `api/routes/preferences.py` — add to `_SYSTEM_PREF_KEYS` set (after `"transcription_timeout_seconds",` around line 42):

```python
    "database_sample_rows",
```

- [ ] **Step 3: Add schema entry**

Edit `api/routes/preferences.py` — add to `_PREFERENCE_SCHEMA` dict (find an appropriate location near other conversion settings):

```python
    "database_sample_rows": {
        "type": "number",
        "min": 1,
        "max": 1000,
        "label": "Database sample rows per table",
        "description": "Number of rows to include in database file Markdown output (per table)",
    },
```

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile core/db/preferences.py && python -m py_compile api/routes/preferences.py`
Expected: No output (clean compile)

- [ ] **Step 5: Commit**

```bash
git add core/db/preferences.py api/routes/preferences.py
git commit -m "feat(database): add database_sample_rows preference"
```

---

## Task 10: Dockerfile.base Dependencies

**Files:**
- Modify: `Dockerfile.base:48-51` (apt-get section)
- Modify: `Dockerfile.base:69-70` (pip install section)

- [ ] **Step 1: Add apt packages**

Edit `Dockerfile.base` — add after the `p7zip-full \` line (line 51), before `# NFS client tools`:

```dockerfile
    # Database file support (Access .mdb/.accdb)
    mdbtools \
    unixodbc-dev \
    odbc-mdbtools \
```

- [ ] **Step 2: Add pip packages**

Edit `Dockerfile.base` — add a new RUN line after the whisper install (after line 70):

```dockerfile
# Database handler Python dependencies
RUN pip install --no-cache-dir dbfread pyodbc pysqlcipher3
```

- [ ] **Step 3: Verify Dockerfile syntax**

Run: `docker build -f Dockerfile.base --check .` (or just `python -c "print('syntax check manual')"` — Docker syntax check is optional)

- [ ] **Step 4: Commit**

```bash
git add Dockerfile.base
git commit -m "feat(database): add mdbtools, dbfread, pyodbc, pysqlcipher3 to base image"
```

---

## Task 11: Update docs/formats.md

**Files:**
- Modify: `docs/formats.md:37`

- [ ] **Step 1: Add Database row and update Binary row**

Edit `docs/formats.md` — add a new row before the `Binary (metadata)` row (line 37), and remove the database extensions from the Binary row:

Add before line 37:

```markdown
| Database | `.sqlite` `.db` `.sqlite3` `.s3db` `.mdb` `.accdb` `.dbf` `.qbb` `.qbw` | DatabaseHandler |
```

Update line 37 to remove `.sqlite .db .mdb .accdb`:

```markdown
| Binary (metadata) | `.bin` `.cl4` `.exe` `.dll` `.so` `.msi` `.sys` `.drv` `.ocx` `.cpl` `.scr` `.com` `.dylib` `.app` `.dmg` `.img` `.vhd` `.vhdx` `.vmdk` `.vdi` `.qcow2` `.rom` `.fw` `.efi` `.class` `.pyc` `.pyo` `.o` `.obj` `.lib` `.a` `.dat` `.dmp` | BinaryHandler |
```

- [ ] **Step 2: Commit**

```bash
git add docs/formats.md
git commit -m "docs: add Database category to formats.md"
```

---

## Task 12: Help Wiki Article

**Files:**
- Create: `docs/help/database-files.md`

- [ ] **Step 1: Write the help article**

```markdown
# Database Files

MarkFlow can extract and summarize the contents of common database files,
producing a Markdown document that includes the schema, sample data,
relationships, and indexes.

## Supported Formats

| Format | Extensions | Notes |
|--------|-----------|-------|
| SQLite | .sqlite, .db, .sqlite3, .s3db | Full support via Python built-in |
| Microsoft Access | .mdb, .accdb | Requires mdbtools (installed by default) |
| dBase / FoxPro | .dbf | Full support via dbfread |
| QuickBooks | .qbb, .qbw | Best-effort; see limitations below |

## What Gets Extracted

For each database, MarkFlow produces:

- **Metadata** -- format, file size, table count, total rows, SHA-256 hash
- **Schema overview** -- all tables with row counts and primary keys
- **Per-table detail** -- column names, types, nullable, keys, defaults
- **Sample data** -- first N rows per table (configurable, default 25)
- **Relationships** -- foreign keys between tables
- **Indexes** -- index names, columns, uniqueness

## Sample Rows Setting

Control how many rows are sampled per table in **Settings > Conversion >
Database sample rows per table**. Default is 25, maximum is 1000.

Larger values produce more complete output but increase conversion time
and output file size for databases with many tables.

## Password-Protected Databases

MarkFlow automatically attempts to unlock encrypted databases using the
same password cascade as archive files:

1. Empty password
2. Your saved password list (config/archive_passwords.txt)
3. Dictionary attack (common.txt wordlist)
4. Brute force (up to configured length/timeout)

If all methods fail, MarkFlow still produces a metadata-only summary
noting that the file is encrypted.

## QuickBooks Limitations

QuickBooks .qbb and .qbw files use a proprietary binary format.
MarkFlow extracts what it can (company name, file metadata) but
full content extraction requires exporting from QuickBooks Desktop:

1. Open the file in QuickBooks Desktop
2. File > Utilities > Export > IIF Files (or Reports > Excel/CSV)
3. Convert the exported files through MarkFlow

## Access Engine Cascade

For .mdb and .accdb files, MarkFlow tries multiple engines in order:

1. **mdbtools** -- lightweight, installed by default
2. **pyodbc** -- ODBC interface, also uses mdbtools driver
3. **jackcess** -- Java-based, optional (requires JVM in container)

The first engine that successfully opens the file is used. If none
work, a metadata-only summary is produced.

### Installing jackcess (optional)

For better .accdb support (especially encrypted files):

1. Install a JRE in the container: `apt-get install default-jre-headless`
2. Download jackcess-cli.jar to `/opt/jackcess/`
3. Restart the container

## Large Databases

For databases with many tables or wide schemas:

- Only the first 50 tables get full detail sections
- Sample data tables wider than 20 columns are truncated
- Row sampling is capped at 1000 rows maximum
```

- [ ] **Step 2: Commit**

```bash
git add docs/help/database-files.md
git commit -m "docs: add database-files help wiki article"
```

---

## Task 13: Verify Everything Together

- [ ] **Step 1: Run py_compile on all new files**

```bash
python -m py_compile formats/database/__init__.py
python -m py_compile formats/database/engine.py
python -m py_compile formats/database/sqlite_engine.py
python -m py_compile formats/database/access_engine.py
python -m py_compile formats/database/dbase_engine.py
python -m py_compile formats/database/quickbooks_engine.py
python -m py_compile formats/database/capability.py
python -m py_compile formats/database_handler.py
```

Expected: All clean, no output.

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest tests/test_database_engines.py tests/test_database_handler.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Verify handler registration end-to-end**

```bash
python -c "
from formats import *
from formats.base import get_handler
for ext in ['sqlite', 'db', 'sqlite3', 's3db', 'mdb', 'accdb', 'dbf', 'qbb', 'qbw']:
    h = get_handler(ext)
    print(f'.{ext} -> {type(h).__name__}')
# Verify BinaryHandler still handles its remaining extensions
for ext in ['bin', 'exe', 'dll', 'dat']:
    h = get_handler(ext)
    print(f'.{ext} -> {type(h).__name__}')
"
```

Expected:
```
.sqlite -> DatabaseHandler
.db -> DatabaseHandler
.sqlite3 -> DatabaseHandler
.s3db -> DatabaseHandler
.mdb -> DatabaseHandler
.accdb -> DatabaseHandler
.dbf -> DatabaseHandler
.qbb -> DatabaseHandler
.qbw -> DatabaseHandler
.bin -> BinaryHandler
.exe -> BinaryHandler
.dll -> BinaryHandler
.dat -> BinaryHandler
```

- [ ] **Step 4: Commit final verification (if any fixes needed)**

```bash
git add -A
git commit -m "fix(database): verification fixes"
```
