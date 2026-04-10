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
