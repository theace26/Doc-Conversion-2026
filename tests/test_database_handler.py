"""Tests for formats/database_handler.py — database file ingest."""

import sqlite3
import pytest
from pathlib import Path

from core.document_model import DocumentModel, Element, ElementType


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
        tables = model.get_elements_by_type(ElementType.TABLE)
        sample_tables = [t for t in tables if t.content and len(t.content) > 1
                         and t.content[0][0] not in ("Property", "Table", "Column", "Relationship", "Index")]
        assert len(sample_tables) >= 1

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
