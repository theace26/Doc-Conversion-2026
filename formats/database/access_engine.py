"""Microsoft Access engine -- mdbtools -> pyodbc -> jackcess cascade."""

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
    return name


class MdbtoolsBackend:
    """Access engine backend using mdbtools CLI."""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("mdb-tables") is not None

    def __init__(self, path: Path, password: str | None = None):
        self._path = path
        self._env: dict[str, str] = {}
        if password:
            self._env["MDB_PASSWORD"] = password

    def _run(self, cmd: list[str], timeout: int = 30) -> str:
        import os
        env = {**os.environ, **self._env} if self._env else None
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
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
        return max(0, len(rows) - 1)


class AccessEngine(DatabaseEngine):
    """Extract schema and data from MS Access .mdb/.accdb files.

    Tries backends in order: mdbtools -> pyodbc -> jackcess.
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
        try:
            with open(path, "rb") as f:
                header = f.read(4)
            if header[:4] not in (b"\x00\x01\x00\x00", b"\x00\x00\x00\x00"):
                pass
        except Exception:
            return False

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

        if self._try_pyodbc(path, password):
            return True
        if self._try_jackcess(path, password):
            return True

        log.warning("access_no_backend", path=str(path))
        return False

    def _try_pyodbc(self, path: Path, password: str | None) -> bool:
        try:
            import pyodbc
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
        type_map: dict[str, str] = {}
        in_table = False
        for line in schema_text.split("\n"):
            stripped = line.strip()
            if (
                stripped.upper().startswith(f"CREATE TABLE [{table}]")
                or stripped.upper().startswith(f'CREATE TABLE "{table}"')
            ):
                in_table = True
                continue
            if in_table and stripped == ");":
                break
            if in_table and stripped and not stripped.startswith("--"):
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
        rels: list[RelationshipInfo] = []
        current_table = ""
        for line in schema_text.split("\n"):
            stripped = line.strip()
            if "CREATE TABLE" in stripped.upper():
                for ch in ("[", '"'):
                    if ch in stripped:
                        start = stripped.index(ch) + 1
                        end_ch = "]" if ch == "[" else '"'
                        end = stripped.index(end_ch, start)
                        current_table = stripped[start:end]
                        break
            if "REFERENCES" in stripped.upper() and current_table:
                parts = stripped.split()
                col_name = parts[0].strip("[]\"").rstrip(",")
                ref_idx = next(
                    (i for i, p in enumerate(parts) if p.upper() == "REFERENCES"),
                    None,
                )
                if ref_idx and ref_idx + 1 < len(parts):
                    ref_part = parts[ref_idx + 1]
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
        return []

    def close(self) -> None:
        self._backend = None
