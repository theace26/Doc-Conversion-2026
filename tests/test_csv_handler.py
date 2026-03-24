"""
Tests for formats/csv_handler.py — CSV/TSV ingest and export.

Covers encoding detection, delimiter handling, edge cases,
and round-trip fidelity.
"""

import pytest
from pathlib import Path

from core.document_model import DocumentModel, Element, ElementType


# ── Ingest ───────────────────────────────────────────────────────────────────

class TestCsvIngest:
    """Tests for CSV ingestion."""

    def test_utf8_csv_ingest(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_csv)

        tables = model.get_elements_by_type(ElementType.TABLE)
        assert len(tables) == 1

        rows = tables[0].content
        assert len(rows) == 11, "Header + 10 data rows"
        assert len(rows[0]) == 5, "5 columns"

    def test_header_row_is_first(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_csv)

        table = model.get_elements_by_type(ElementType.TABLE)[0]
        assert table.content[0] == ["id", "name", "age", "city", "score"]

    def test_utf8_bom_handled(self, tmp_path):
        """UTF-8-BOM CSV should be read correctly without BOM artifact."""
        from formats.csv_handler import CsvHandler

        path = tmp_path / "bom.csv"
        content = "\ufeffid,name\n1,Alice\n2,Bob\n"
        path.write_text(content, encoding="utf-8-sig")

        handler = CsvHandler()
        model = handler.ingest(path)

        table = model.get_elements_by_type(ElementType.TABLE)[0]
        # First column name should not have BOM artifact
        assert table.content[0][0] == "id"

    def test_latin1_encoding_detection(self, latin1_csv_path):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(latin1_csv_path)

        table = model.get_elements_by_type(ElementType.TABLE)[0]
        assert len(table.content) == 4  # header + 3 rows
        # Check that accented characters survived
        names = [row[1] for row in table.content[1:]]
        assert "José" in names

    def test_tsv_detected(self, simple_tsv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_tsv)

        table = model.get_elements_by_type(ElementType.TABLE)[0]
        assert len(table.content[0]) == 3, "TSV has 3 columns"

    def test_page_count_is_one(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_csv)

        assert model.metadata.page_count == 1

    def test_source_format_csv(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_csv)

        assert model.metadata.source_format == "csv"

    def test_source_format_tsv(self, simple_tsv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_tsv)

        assert model.metadata.source_format == "tsv"


# ── Ingest edge cases ───────────────────────────────────────────────────────

class TestCsvIngestEdgeCases:
    """Edge case tests for CSV ingest."""

    def test_empty_csv_produces_warning(self, tmp_path):
        from formats.csv_handler import CsvHandler

        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")

        handler = CsvHandler()
        model = handler.ingest(path)

        assert len(model.warnings) > 0
        tables = model.get_elements_by_type(ElementType.TABLE)
        assert len(tables) == 0

    def test_single_column_csv(self, tmp_path):
        from formats.csv_handler import CsvHandler

        path = tmp_path / "single.csv"
        path.write_text("name\nAlice\nBob\nCharlie\n", encoding="utf-8")

        handler = CsvHandler()
        model = handler.ingest(path)

        table = model.get_elements_by_type(ElementType.TABLE)[0]
        assert len(table.content[0]) == 1

    def test_unicode_csv(self, unicode_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(unicode_csv)

        table = model.get_elements_by_type(ElementType.TABLE)[0]
        assert len(table.content) >= 2
        # Check CJK characters survived
        all_text = str(table.content)
        assert "田中" in all_text or "José" in all_text


# ── Export ───────────────────────────────────────────────────────────────────

class TestCsvExport:
    """Tests for TABLE → CSV export."""

    def test_round_trip_row_count(self, simple_csv, tmp_path):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_csv)

        output = tmp_path / "output.csv"
        handler.export(model, output)

        model2 = handler.ingest(output)
        orig_table = model.get_elements_by_type(ElementType.TABLE)[0]
        new_table = model2.get_elements_by_type(ElementType.TABLE)[0]

        assert len(new_table.content) == len(orig_table.content)
        assert len(new_table.content[0]) == len(orig_table.content[0])

    def test_tsv_delimiter_preserved(self, simple_tsv, tmp_path):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        model = handler.ingest(simple_tsv)

        output = tmp_path / "output.tsv"
        handler.export(model, output)

        content = output.read_text(encoding="utf-8")
        # TSV should use tabs, not commas
        assert "\t" in content

    def test_utf8_output(self, tmp_path):
        from formats.csv_handler import CsvHandler

        model = DocumentModel()
        model.add_element(Element(
            type=ElementType.TABLE,
            content=[["name", "city"], ["José", "São Paulo"]],
        ))

        handler = CsvHandler()
        output = tmp_path / "utf8.csv"
        handler.export(model, output)

        content = output.read_text(encoding="utf-8")
        assert "José" in content

    def test_empty_table_export(self, tmp_path):
        from formats.csv_handler import CsvHandler

        model = DocumentModel()
        handler = CsvHandler()
        output = tmp_path / "empty.csv"
        handler.export(model, output)
        assert output.exists()


class TestCsvStyleExtraction:
    """Tests for CSV style extraction."""

    def test_extract_styles_returns_dict(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        styles = handler.extract_styles(simple_csv)
        assert isinstance(styles, dict)
        assert "document_level" in styles

    def test_extract_styles_has_delimiter(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        styles = handler.extract_styles(simple_csv)
        assert styles["document_level"]["delimiter"] == ","

    def test_extract_styles_tsv_delimiter(self, simple_tsv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        styles = handler.extract_styles(simple_tsv)
        assert styles["document_level"]["delimiter"] == "\t"

    def test_extract_styles_encoding(self, simple_csv):
        from formats.csv_handler import CsvHandler

        handler = CsvHandler()
        styles = handler.extract_styles(simple_csv)
        assert "encoding" in styles["document_level"]

    def test_supports_format(self):
        from formats.csv_handler import CsvHandler

        assert CsvHandler.supports_format("csv")
        assert CsvHandler.supports_format("tsv")
        assert CsvHandler.supports_format(".csv")
        assert not CsvHandler.supports_format("xlsx")
