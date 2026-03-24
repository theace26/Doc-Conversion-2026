"""
CSV/TSV format handler — tabular data extraction and reconstruction.

Ingest:
  Reads via pandas with encoding detection and delimiter auto-detect.
  Falls back to stdlib csv.reader on parse errors.
  First row treated as header.

Export:
  Writes via pandas with sidecar-stored delimiter and encoding.
  No Tier 2/3 — CSV has no styles.
"""

import csv
import io
import logging
from pathlib import Path
from typing import Any

from formats.base import FormatHandler, register_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)

log = logging.getLogger(__name__)

# Encoding detection order
_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]


@register_handler
class CsvHandler(FormatHandler):
    EXTENSIONS = ["csv", "tsv"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        model = DocumentModel()
        ext = file_path.suffix.lower()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext.lstrip("."),
        )

        delimiter = "\t" if ext == ".tsv" else ","
        encoding = self._detect_encoding(file_path)

        rows = self._read_with_pandas(file_path, delimiter, encoding)
        if rows is None:
            rows = self._read_with_stdlib(file_path, delimiter, encoding)

        if not rows:
            model.warnings.append("Empty CSV/TSV file — no data extracted.")
            return model

        model.metadata.page_count = 1
        model.add_element(Element(type=ElementType.TABLE, content=rows))

        # Store ingest metadata for export fidelity
        model.style_data["csv_delimiter"] = delimiter
        model.style_data["csv_encoding"] = encoding

        return model

    def _detect_encoding(self, file_path: Path) -> str:
        """Try reading the file with various encodings."""
        raw = file_path.read_bytes()
        for enc in _ENCODINGS:
            try:
                raw.decode(enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue
        return "latin-1"  # Last resort — always succeeds

    def _read_with_pandas(
        self, file_path: Path, delimiter: str, encoding: str
    ) -> list[list[str]] | None:
        """Try reading with pandas. Returns list of rows or None on failure."""
        try:
            import pandas as pd

            df = pd.read_csv(
                str(file_path),
                sep=delimiter,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
            )

            rows: list[list[str]] = []
            # Header row
            rows.append([str(col) for col in df.columns])
            # Data rows
            for _, row in df.iterrows():
                rows.append([str(val) for val in row])

            return rows
        except Exception as exc:
            log.debug("csv.pandas_read_failed", error=str(exc))
            return None

    def _read_with_stdlib(
        self, file_path: Path, delimiter: str, encoding: str
    ) -> list[list[str]]:
        """Fallback: read with stdlib csv.reader."""
        rows: list[list[str]] = []
        try:
            with open(file_path, newline="", encoding=encoding) as f:
                reader = csv.reader(f, delimiter=delimiter)
                for row in reader:
                    rows.append([str(cell) for cell in row])
        except Exception as exc:
            log.warning("csv.stdlib_read_failed", error=str(exc))
        return rows

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        # Determine delimiter and encoding from sidecar or output extension
        ext = output_path.suffix.lower()
        delimiter = "\t" if ext == ".tsv" else ","
        encoding = "utf-8"

        if sidecar:
            doc_level = sidecar.get("document_level", {})
            delimiter = doc_level.get("delimiter", delimiter)
            encoding = doc_level.get("encoding", encoding)

        # Find the table element
        tables = model.get_elements_by_type(ElementType.TABLE)
        if not tables:
            output_path.write_text("", encoding=encoding)
            return

        rows = tables[0].content
        if not isinstance(rows, list) or not rows:
            output_path.write_text("", encoding=encoding)
            return

        self._write_with_pandas(rows, output_path, delimiter, encoding)

    def _write_with_pandas(
        self,
        rows: list[list[str]],
        output_path: Path,
        delimiter: str,
        encoding: str,
    ) -> None:
        """Write rows to CSV/TSV via pandas."""
        try:
            import pandas as pd

            headers = rows[0] if rows else []
            data = rows[1:] if len(rows) > 1 else []
            df = pd.DataFrame(data, columns=headers)
            df.to_csv(str(output_path), sep=delimiter, index=False, encoding=encoding)
        except Exception as exc:
            log.debug("csv.pandas_write_failed", error=str(exc))
            # Fallback to stdlib
            with open(output_path, "w", newline="", encoding=encoding) as f:
                writer = csv.writer(f, delimiter=delimiter)
                writer.writerows(rows)

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """CSV has minimal styles — capture delimiter, encoding, dtypes."""
        ext = file_path.suffix.lower()
        delimiter = "\t" if ext == ".tsv" else ","
        encoding = self._detect_encoding(file_path)

        styles: dict[str, Any] = {
            "document_level": {
                "delimiter": delimiter,
                "encoding": encoding,
                "extension": ext,
            }
        }

        # Detect column types via pandas
        try:
            import pandas as pd

            df = pd.read_csv(str(file_path), sep=delimiter, encoding=encoding, nrows=100)
            dtypes: dict[str, str] = {}
            for col in df.columns:
                dtypes[str(col)] = str(df[col].dtype)
            styles["document_level"]["column_dtypes"] = dtypes
            styles["document_level"]["has_header"] = True
        except Exception:
            pass

        return styles

    @classmethod
    def supports_format(cls, extension: str) -> bool:
        return extension.lower().lstrip(".") in cls.EXTENSIONS
