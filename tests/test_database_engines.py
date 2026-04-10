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


import sqlite3
from formats.database.sqlite_engine import SQLiteEngine


@pytest.fixture
def sample_sqlite(tmp_path):
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
