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
