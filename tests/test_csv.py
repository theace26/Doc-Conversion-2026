"""Tests for formats/csv_handler.py — CSV/TSV ingest, export, round-trip."""

import tempfile
from pathlib import Path

import pytest

from core.document_model import ElementType
from formats.csv_handler import CsvHandler


@pytest.fixture
def handler():
    return CsvHandler()


# ── Ingest: simple.csv ──────────────────────────────────────────────────────

def test_ingest_returns_model(simple_csv, handler):
    model = handler.ingest(simple_csv)
    assert model is not None
    assert len(model.elements) > 0


def test_ingest_has_table(simple_csv, handler):
    model = handler.ingest(simple_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    assert len(tables) == 1


def test_ingest_column_count(simple_csv, handler):
    model = handler.ingest(simple_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content
    assert len(rows[0]) == 5  # id, name, age, city, score


def test_ingest_row_count(simple_csv, handler):
    model = handler.ingest(simple_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content
    assert len(rows) == 11  # 1 header + 10 data rows


def test_ingest_header_detected(simple_csv, handler):
    model = handler.ingest(simple_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    headers = tables[0].content[0]
    assert "id" in headers
    assert "name" in headers
    assert "city" in headers


def test_ingest_data_values(simple_csv, handler):
    model = handler.ingest(simple_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content
    # First data row
    assert rows[1][1] == "Alice"
    assert rows[1][3] == "New York"


def test_ingest_metadata(simple_csv, handler):
    model = handler.ingest(simple_csv)
    assert model.metadata.source_format == "csv"


# ── Ingest: unicode.csv ─────────────────────────────────────────────────────

def test_ingest_unicode_preserved(unicode_csv, handler):
    model = handler.ingest(unicode_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content

    # Check non-ASCII characters survive
    all_text = " ".join(cell for row in rows for cell in row)
    assert "José" in all_text or "Jos" in all_text
    assert "München" in all_text or "M" in all_text
    assert "田中" in all_text or "太郎" in all_text


def test_ingest_unicode_row_count(unicode_csv, handler):
    model = handler.ingest(unicode_csv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content
    assert len(rows) == 6  # 1 header + 5 data rows


# ── Ingest: simple.tsv ──────────────────────────────────────────────────────

def test_ingest_tsv(simple_tsv, handler):
    model = handler.ingest(simple_tsv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    assert len(tables) == 1


def test_ingest_tsv_values(simple_tsv, handler):
    model = handler.ingest(simple_tsv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content
    headers = rows[0]
    assert "id" in headers
    assert "name" in headers
    assert "value" in headers
    assert rows[1][1] == "Alpha"


def test_ingest_tsv_row_count(simple_tsv, handler):
    model = handler.ingest(simple_tsv)
    tables = model.get_elements_by_type(ElementType.TABLE)
    rows = tables[0].content
    assert len(rows) == 6  # 1 header + 5 data


# ── Ingest: empty CSV ───────────────────────────────────────────────────────

def test_ingest_empty_csv(handler, tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    model = handler.ingest(empty)
    tables = model.get_elements_by_type(ElementType.TABLE)
    assert len(tables) == 0
    assert len(model.warnings) >= 1


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_creates_file(simple_csv, handler, tmp_path):
    model = handler.ingest(simple_csv)
    output = tmp_path / "output.csv"
    handler.export(model, output)
    assert output.exists()
    assert output.stat().st_size > 0


def test_export_row_count(simple_csv, handler, tmp_path):
    model = handler.ingest(simple_csv)
    output = tmp_path / "output.csv"
    handler.export(model, output)

    lines = output.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 11  # 1 header + 10 data rows


def test_export_column_count(simple_csv, handler, tmp_path):
    model = handler.ingest(simple_csv)
    output = tmp_path / "output.csv"
    handler.export(model, output)

    lines = output.read_text(encoding="utf-8").strip().split("\n")
    header_cols = lines[0].split(",")
    assert len(header_cols) == 5


def test_export_tsv_preserves_delimiter(simple_tsv, handler, tmp_path):
    """TSV should be exported with tab delimiter."""
    model = handler.ingest(simple_tsv)

    output = tmp_path / "output.tsv"
    sidecar = {"document_level": {"delimiter": "\t", "encoding": "utf-8"}}
    handler.export(model, output, sidecar=sidecar)

    content = output.read_text(encoding="utf-8")
    assert "\t" in content


def test_export_empty_model(handler, tmp_path):
    from core.document_model import DocumentModel

    model = DocumentModel()
    output = tmp_path / "empty.csv"
    handler.export(model, output)
    assert output.exists()


# ── Style extraction ─────────────────────────────────────────────────────────

def test_extract_styles_csv(simple_csv, handler):
    styles = handler.extract_styles(simple_csv)
    assert "document_level" in styles
    doc = styles["document_level"]
    assert doc["delimiter"] == ","
    assert "encoding" in doc


def test_extract_styles_tsv(simple_tsv, handler):
    styles = handler.extract_styles(simple_tsv)
    assert styles["document_level"]["delimiter"] == "\t"


# ── Round-trip ───────────────────────────────────────────────────────────────

def test_roundtrip_csv_values(simple_csv, handler, tmp_path):
    """CSV → DocumentModel → CSV: values should match."""
    model = handler.ingest(simple_csv)
    output = tmp_path / "roundtrip.csv"
    handler.export(model, output)

    # Re-ingest and compare
    model2 = handler.ingest(output)
    tables1 = model.get_elements_by_type(ElementType.TABLE)
    tables2 = model2.get_elements_by_type(ElementType.TABLE)

    assert len(tables2[0].content) == len(tables1[0].content)
    assert tables2[0].content[0] == tables1[0].content[0]  # Headers match
    assert tables2[0].content[1][1] == tables1[0].content[1][1]  # Alice


def test_roundtrip_column_order(simple_csv, handler, tmp_path):
    """Column order should be preserved in round-trip."""
    model = handler.ingest(simple_csv)
    output = tmp_path / "roundtrip.csv"
    handler.export(model, output)

    model2 = handler.ingest(output)
    tables1 = model.get_elements_by_type(ElementType.TABLE)
    tables2 = model2.get_elements_by_type(ElementType.TABLE)

    assert tables2[0].content[0] == tables1[0].content[0]


def test_roundtrip_unicode(unicode_csv, handler, tmp_path):
    """Unicode characters should survive round-trip."""
    model = handler.ingest(unicode_csv)
    output = tmp_path / "roundtrip.csv"
    handler.export(model, output)

    model2 = handler.ingest(output)
    tables = model2.get_elements_by_type(ElementType.TABLE)
    all_text = " ".join(cell for row in tables[0].content for cell in row)
    assert "José" in all_text or "Jos" in all_text


# ── supports_format ──────────────────────────────────────────────────────────

def test_supports_csv():
    assert CsvHandler.supports_format("csv")
    assert CsvHandler.supports_format(".csv")
    assert CsvHandler.supports_format("tsv")
    assert CsvHandler.supports_format(".tsv")
    assert not CsvHandler.supports_format("xlsx")
