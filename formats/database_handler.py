"""
Database file handler — SQLite, Access, dBase, QuickBooks.

Ingest:
  Extracts schema, metadata, sample data, relationships, and indexes
  into a structured Markdown DocumentModel.

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

        password = kwargs.get("password")
        opened = engine.open(file_path, password)

        if not opened and not password:
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
                 engine=engine_type)
        return model

    def _build_model(
        self, model: DocumentModel, engine: DatabaseEngine, file_path: Path, sample_limit: int
    ) -> None:
        tables = engine.list_tables()
        total_rows = sum(t.row_count for t in tables)
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        engine_name = getattr(engine, "backend_name", type(engine).__name__)

        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"Database: {file_path.name}",
            level=1,
        ))

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

            if t.row_count > 0:
                rows = engine.sample_rows(t.name, limit=sample_limit)
                if rows and len(rows) > 1:
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
        from pathlib import Path as _Path

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
