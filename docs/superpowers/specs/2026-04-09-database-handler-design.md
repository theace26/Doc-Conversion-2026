# Database File Handler — Design Spec

**Date:** 2026-04-09
**Branch:** `vector`
**Status:** Approved

---

## Goal

Add a `DatabaseHandler` that extracts schema, metadata, and sample data from
database files and produces structured Markdown summaries. Replaces the current
`BinaryHandler` (metadata-only) registration for database extensions.

The output answers two questions: **what does this database do?** and **what
information is in it?**

---

## Supported Formats

| Format | Extensions | Engine | Dependencies |
|--------|-----------|--------|--------------|
| SQLite | `.sqlite`, `.db`, `.sqlite3`, `.s3db` | `sqlite3` (built-in) | None |
| MS Access 97-2003 | `.mdb` | `mdbtools` -> `pyodbc` -> `jackcess` cascade | `mdbtools` (apt) |
| MS Access 2007+ | `.accdb` | same cascade | same |
| dBase / FoxPro | `.dbf` | `dbfread` | `dbfread` (pip, pure Python) |
| QuickBooks | `.qbb`, `.qbw` | Binary header parse + BTrieve extraction | None (best-effort) |

---

## Engine Architecture

### Common Interface

Each database format is backed by an engine class implementing:

```python
class DatabaseEngine(ABC):
    """Abstract interface for database content extraction."""

    @abstractmethod
    def can_open(self, path: Path, password: str | None = None) -> bool:
        """Test whether this engine can open the file."""

    @abstractmethod
    def list_tables(self) -> list[TableInfo]:
        """Return table names with row counts."""

    @abstractmethod
    def get_schema(self, table: str) -> list[ColumnInfo]:
        """Return column definitions for a table."""

    @abstractmethod
    def get_row_count(self, table: str) -> int:
        """Return exact row count for a table."""

    @abstractmethod
    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        """Return the first N rows as string values."""

    @abstractmethod
    def get_relationships(self) -> list[RelationshipInfo]:
        """Return foreign key / relationship definitions."""

    @abstractmethod
    def get_indexes(self) -> list[IndexInfo]:
        """Return index definitions."""

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
```

Supporting dataclasses:

```python
@dataclass
class TableInfo:
    name: str
    row_count: int
    column_count: int

@dataclass
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    default_value: str | None = None

@dataclass
class RelationshipInfo:
    name: str
    parent_table: str
    child_table: str
    parent_columns: list[str]
    child_columns: list[str]

@dataclass
class IndexInfo:
    name: str
    table: str
    columns: list[str]
    unique: bool
```

### Engine Implementations

#### SQLiteEngine

- Uses Python built-in `sqlite3` module.
- Schema from `sqlite_master` + `PRAGMA table_info()`.
- Relationships from `PRAGMA foreign_key_list()`.
- Indexes from `PRAGMA index_list()` + `PRAGMA index_info()`.
- Encrypted databases: detect SQLCipher via file magic bytes
  (`SQLite format 3\x00` absent = likely encrypted). Use `pysqlcipher3`
  if available.

#### AccessEngine

Automatic cascade — try each engine in order, use the first that succeeds:

1. **mdbtools** (lightest): Shell out to `mdb-tables`, `mdb-schema`,
   `mdb-export`. Available via `apt-get install mdbtools` (~2 MB).
   Good `.mdb` support; `.accdb` support partial but improving.

2. **pyodbc** + mdbtools ODBC driver: SQL-standard interface via ODBC.
   Still `mdbtools` under the hood but allows parameterized queries.

3. **jackcess** (Java): Excellent `.accdb` support including encrypted
   files. Requires JVM in container — **opt-in dependency**, not
   installed by default. Invoked via subprocess
   (`java -jar jackcess-cli.jar`).

Cascade logic:
```
for engine in [MdbtoolsEngine, PyodbcEngine, JackcessEngine]:
    if engine.is_available() and engine.can_open(path, password):
        return engine
raise DatabaseUnreadableError(path, tried=[...])
```

#### DBaseEngine

- Uses `dbfread` (pure Python, pip install).
- Schema from `DBF.fields` (name, type, length, decimal_count).
- No relationships or indexes (dBase doesn't have them).
- Handles common encodings (CP437, CP1252, UTF-8).

#### QuickBooksEngine

Best-effort binary extraction for a proprietary format:

- **Header parsing:** Company name, QB version, creation date are at
  known offsets in the file header.
- **Older files (pre-2006):** Used a modified BTrieve/Paradox engine.
  Table names and some field data are extractable from the binary
  structure.
- **Newer/encrypted files:** Metadata-only output. The Markdown
  includes explicit instructions for exporting via QuickBooks Desktop
  (File -> Utilities -> Export -> IIF/CSV).
- **`.qbb` files:** These are backup archives. Attempt to decompress
  (they use a custom compression) and then parse the inner `.qbw`.

---

## Engine Cascade for Password-Protected Databases

Plugs into the existing `core/password_cascade.py` infrastructure
(same system the archive handler uses):

1. Attempt to open without a password.
2. If encrypted, run the full cascade:
   - Empty password
   - Static password list (`passwords.txt`)
   - Dictionary attack
   - Brute force
3. Format-specific encryption handling:
   - **SQLite/SQLCipher:** `pysqlcipher3` with `PRAGMA key = ?`
   - **Access:** `mdbtools` via `MDB_JET3_ENCRYPT` / `MDB_PASSWORD`
     env vars; `jackcess` has native `DatabaseBuilder.open(file, pwd)`
   - **QuickBooks:** Attempt known default passwords, then cascade;
     if all fail -> metadata-only with export instructions
4. On success, record which password worked in the conversion log
   (same pattern as archive handler).

---

## Markdown Output Structure

### Standard Database (SQLite, Access, dBase)

```markdown
# Database: filename.accdb

| Property | Value |
|----------|-------|
| Format | Microsoft Access 2007+ |
| Size | 14.2 MB |
| Tables | 23 |
| Total Rows | 148,392 |
| Engine | mdbtools |
| SHA-256 | `abc123...` |

## Summary

[AI-generated 2-3 sentence summary if AI Assist is enabled and a
provider is configured. Describes what the database appears to contain
based on table/column names. Omitted if no LLM provider available.]

## Schema Overview

| Table | Rows | Columns | Primary Key |
|-------|------|---------|-------------|
| Members | 4,201 | 18 | MemberID |
| DuesPayments | 52,340 | 9 | PaymentID |
| Dispatches | 12,887 | 14 | DispatchID |
| ... | | | |

## Table: Members

**Columns:**

| Column | Type | Nullable | Key | Default |
|--------|------|----------|-----|---------|
| MemberID | INTEGER | NO | PK | |
| LastName | VARCHAR(50) | NO | | |
| FirstName | VARCHAR(50) | NO | | |
| HireDate | DATETIME | YES | | |
| ... | | | | |

**Sample Data (first 25 rows):**

| MemberID | LastName | FirstName | HireDate | ... |
|----------|----------|-----------|----------|-----|
| 1001 | Smith | John | 2019-03-15 | ... |
| 1002 | Garcia | Maria | 2020-01-10 | ... |
| ... | | | | |

[Repeat "## Table: ..." section for each table]

## Relationships

| Relationship | Parent Table | Child Table | Columns |
|-------------|-------------|-------------|---------|
| FK_Dues_Member | Members | DuesPayments | MemberID -> MemberID |
| FK_Dispatch_Member | Members | Dispatches | MemberID -> MemberID |

## Indexes

| Index | Table | Columns | Unique |
|-------|-------|---------|--------|
| idx_member_last | Members | LastName | NO |
| PK_Members | Members | MemberID | YES |
```

### QuickBooks (Limited Extraction)

```markdown
# Database: CompanyFile.qbw

| Property | Value |
|----------|-------|
| Format | QuickBooks Working File |
| Size | 89.4 MB |
| Company Name | IBEW Local 46 |
| QB Version | 2023 |
| Encryption | AES-256 |
| Content Accessible | Partial |

## Extracted Content

[Tables/fields extracted from the binary structure, rendered as
schema + sample data sections identical to the standard format above]

## Inaccessible Content

This file uses QuickBooks proprietary encryption. For full content
extraction, export from QuickBooks Desktop:

1. Open the file in QuickBooks Desktop
2. File -> Utilities -> Export -> IIF Files (or Reports -> Excel/CSV)
3. Convert the exported IIF/CSV files through MarkFlow

Supported export formats: IIF (tab-delimited), CSV, Excel (.xlsx)
```

---

## Handler Registration

```python
@register_handler
class DatabaseHandler(FormatHandler):
    EXTENSIONS = [
        "sqlite", "db", "sqlite3", "s3db",   # SQLite
        "mdb", "accdb",                        # Access
        "dbf",                                 # dBase / FoxPro
        "qbb", "qbw",                          # QuickBooks
    ]
```

This **replaces** the `BinaryHandler` registration for `.sqlite`, `.db`,
`.mdb`, `.accdb`. The remaining binary formats stay on `BinaryHandler`.

### Export

`export()` raises `NotImplementedError`. Databases are ingest-only — a
Markdown summary cannot be meaningfully reconstructed back into a
database. The Markdown IS the conversion artifact.

### extract_styles

Returns minimal metadata for the style sidecar:

```python
{
    "document_level": {
        "format": "sqlite",
        "engine_used": "sqlite3",
        "table_count": 23,
        "total_rows": 148392,
        "encrypted": False,
    }
}
```

---

## Configuration

| Preference key | Default | UI | Description |
|---------------|---------|-----|-------------|
| `database_sample_rows` | 25 | Settings -> Conversion | Rows to sample per table |

- Hard cap at 1000 rows to prevent multi-GB Markdown output.
- Applies globally to all database conversions.

---

## Capability Detection

At startup (during lifespan), probe for available database engines
and cache in `worker_capabilities.json`:

```json
{
    "database_engines": {
        "sqlite3": true,
        "mdbtools": true,
        "pyodbc_mdbtools": false,
        "jackcess": false,
        "dbfread": true,
        "pysqlcipher3": false
    }
}
```

The handler reads this at conversion time to know which engines to
attempt. If no engine can open a file, fall back to `BinaryHandler`
behavior (metadata-only) with a warning explaining what to install.

---

## Dependencies

### Dockerfile.base (installed by default)

```dockerfile
RUN apt-get install -y mdbtools
RUN pip install dbfread pysqlcipher3
```

- `mdbtools`: ~2 MB, covers Access files
- `dbfread`: pure Python, ~50 KB, covers dBase
- `pysqlcipher3`: C extension for encrypted SQLite (~1 MB compiled)

### Optional (documented, not default)

- **Java JRE + jackcess JAR**: for full `.accdb` support including
  encrypted Access 2007+ files. Install instructions in help wiki.
  Not included by default to keep image size manageable.

### pyodbc + mdbtools ODBC

```dockerfile
RUN apt-get install -y unixodbc-dev odbc-mdbtools
RUN pip install pyodbc
```

Included by default as it's lightweight and provides a better SQL
interface for complex Access queries.

---

## File Layout

```
formats/
    database_handler.py          # Main handler (FormatHandler subclass)
    database/
        __init__.py
        engine.py                # ABC + dataclasses (DatabaseEngine, TableInfo, etc.)
        sqlite_engine.py         # SQLiteEngine
        access_engine.py         # AccessEngine (cascade logic)
        dbase_engine.py          # DBaseEngine
        quickbooks_engine.py     # QuickBooksEngine
        capability.py            # Engine availability detection
```

---

## Error Handling

- **Corrupt files:** Return partial model with `model.warnings.append()`
  describing what failed. Never crash the batch.
- **Missing engines:** Fall back to `BinaryHandler`-style metadata-only
  output. Warning: "Install mdbtools for full Access database extraction."
- **Huge databases (100+ tables):** Schema overview table lists all
  tables but only the first 50 tables get full "## Table: ..." sections.
  Remaining tables noted as "N additional tables not shown."
- **Wide tables (50+ columns):** Sample data table truncates to first
  20 columns with a note: "Showing 20 of N columns."
- **Password cascade failure:** Metadata-only output noting the file
  is encrypted and which methods were tried.

---

## Integration Checklist

- [ ] Create `formats/database/` package with engine modules
- [ ] Create `formats/database_handler.py`
- [ ] Update `formats/__init__.py` — add `database_handler` import
- [ ] Update `BinaryHandler.EXTENSIONS` — remove database extensions
- [ ] Add capability detection to lifespan startup
- [ ] Update `worker_capabilities.json` schema
- [ ] Update `Dockerfile.base` — install `mdbtools`, `pyodbc`, `dbfread`, `pysqlcipher3`
- [ ] Update `docs/formats.md` — new "Database" category
- [ ] Add `docs/help/database-files.md` help article
- [ ] Add `database_sample_rows` preference with default 25
- [ ] Wire password cascade for encrypted databases
- [ ] Update `docs/version-history.md` on release
