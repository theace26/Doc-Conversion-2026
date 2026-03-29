# MarkFlow Patch: Compressed File Scanning + File Tracking

**Version target:** Bump version in CLAUDE.md after applying  
**Scope:** New archive format handlers, archive content conversion pipeline, file size/timestamp/hash tracking for deduplication and change detection  
**Prerequisite:** Read `CLAUDE.md` before touching any file. It is the source of truth for current file paths, table names, handler patterns, and format registry structure.

---

## 0. Overview

This patch adds two major capabilities:

### A. Compressed File Scanning & Indexing
- Support for: `.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`, `.7z`, `.rar`, `.cab`, `.iso`
- Extract every file inside an archive and run it through the full conversion pipeline
- Generate a summary `.md` for each archive (table of contents of all members) PLUS individual `.md` files for every convertible document found inside
- Recursive: archives inside archives are processed, up to 20 levels deep
- Password-protected archives: try passwords from a user-configurable list, skip if all fail
- Zip-bomb protection: configurable max decompressed size (default 50GB)
- Aggressive temp cleanup: per-archive temp directory, wiped immediately after processing completes

### B. File Tracking for Deduplication & Change Detection
- Track `file_size`, `modified_at` (mtime), and `content_hash` (SHA-256) for every file — including files inside archives
- New `archive_members` table linking inner files to their parent archive with their own size/date/hash
- Bulk scanner uses size + mtime + hash to detect changes and skip true duplicates
- If a single file inside an archive changes (archive re-downloaded with updated content), the scanner detects the archive-level mtime change, re-extracts, and compares member hashes to only re-convert changed inner files

---

## 1. Dependencies

### 1.1 Python packages to add to `requirements.txt`

```
py7zr>=0.21.0
rarfile>=4.1
pycdlib>=1.14.0
```

**Do NOT add** packages for `.zip`, `.tar`, `.cab` — these use Python stdlib:
- `zipfile` (stdlib) — .zip
- `tarfile` (stdlib) — .tar, .tar.gz, .tar.bz2, .tar.xz
- `zipfile` or `shutil.unpack_archive` — .cab (via `expand` system command fallback)

**rarfile** requires the `unrar` binary. Add to `Dockerfile`:
```dockerfile
RUN apt-get update && apt-get install -y unrar-free
```

If `unrar-free` is not available in the base image's apt repos, use `unrar` or add the contrib repo. Verify with:
```bash
docker exec <container> which unrar
```

**pycdlib** handles `.iso` (ISO 9660 / UDF disc images) natively in Python — no system dependency needed.

### 1.2 Dockerfile changes

Add to the `apt-get install` line (find the existing one, don't create a second):
```
unrar-free p7zip-full
```

`p7zip-full` is a fallback — `py7zr` handles most `.7z` files natively, but some compression methods (e.g., LZMA2 with BCJ filter) need the system `7z` binary. Having both ensures coverage.

### 1.3 Config file

Create `config/archive_passwords.txt` with a starter set:

```
password
Password
1234
12345
123456
password1
Password1
```

One password per line. Blank lines and lines starting with `#` are ignored.
Add to `.gitignore`:
```
# Archive passwords may contain sensitive info
# config/archive_passwords.txt  <-- commented out so the starter file IS committed
```

Add to `docker-compose.yml` as a bind mount:
```yaml
volumes:
  - ./config:/app/config:ro
```

Verify this doesn't conflict with existing volume mounts. If `./config` is already mounted, just ensure `archive_passwords.txt` lands inside it.

---

## 2. SQLite Schema Changes

### 2.1 Find the existing migration / schema setup

```bash
grep -rn "CREATE TABLE\|file_path\|mtime\|processed_files\|bulk_files\|conversion_history" core/ db/ --include="*.py"
```

Identify the table(s) that track processed files for incremental scanning. The bulk scanner likely uses a table with columns like `file_path`, `status`, `mtime` or similar.

### 2.2 Add columns to the existing file tracking table

Add these columns to whatever table tracks processed files (likely `bulk_files` or `processed_files` or `conversion_records` — CHECK CLAUDE.md and grep results):

```sql
ALTER TABLE <existing_table> ADD COLUMN file_size INTEGER;
ALTER TABLE <existing_table> ADD COLUMN content_hash TEXT;
ALTER TABLE <existing_table> ADD COLUMN modified_at TEXT;  -- ISO 8601 timestamp of source file mtime
```

**IMPORTANT:** Check if `mtime` or `modified_at` already exists under a different name. Don't create duplicates. If `mtime` exists as an integer (epoch), keep it — just add `file_size` and `content_hash`.

Use the project's existing migration pattern. If there's no formal migration system, add the `ALTER TABLE` statements wrapped in try/except (column may already exist):

```python
async def migrate_file_tracking(db):
    """Add file tracking columns if they don't exist."""
    for col, col_type in [
        ("file_size", "INTEGER"),
        ("content_hash", "TEXT"),
        ("modified_at", "TEXT"),
    ]:
        try:
            await db.execute(f"ALTER TABLE <table_name> ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # Column already exists
```

### 2.3 New table: `archive_members`

```sql
CREATE TABLE IF NOT EXISTS archive_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_file_id INTEGER NOT NULL,       -- FK to the parent archive's row in the main file table
    member_path TEXT NOT NULL,              -- path inside the archive (e.g., "docs/report.docx")
    member_size INTEGER,                   -- uncompressed size in bytes
    member_modified_at TEXT,               -- mtime from archive metadata (ISO 8601)
    member_hash TEXT,                      -- SHA-256 of the extracted member content
    status TEXT DEFAULT 'pending',         -- pending, converted, skipped, error
    output_path TEXT,                      -- path to the generated .md in the output repo
    error_message TEXT,                    -- if status='error', what went wrong
    is_archive INTEGER DEFAULT 0,         -- 1 if this member is itself an archive (nested)
    nesting_depth INTEGER DEFAULT 1,      -- depth level (1 = direct child of top-level archive)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (archive_file_id) REFERENCES <existing_table>(id)
);

CREATE INDEX IF NOT EXISTS idx_archive_members_archive_id ON archive_members(archive_file_id);
CREATE INDEX IF NOT EXISTS idx_archive_members_hash ON archive_members(member_hash);
CREATE INDEX IF NOT EXISTS idx_archive_members_status ON archive_members(status);
```

Replace `<existing_table>` with the actual table name from your grep results.

### 2.4 Deduplication via content_hash

Before converting an archive member, check if another record with the same `content_hash` already has `status='converted'` and a valid `output_path`:

```python
async def find_duplicate(db, content_hash: str) -> Optional[str]:
    """Check if a file with this hash has already been converted. Returns output_path or None."""
    row = await db.execute_fetchone(
        """SELECT output_path FROM archive_members WHERE member_hash = ? AND status = 'converted' AND output_path IS NOT NULL
           UNION ALL
           SELECT output_path FROM <existing_table> WHERE content_hash = ? AND status = 'success' AND output_path IS NOT NULL
           LIMIT 1""",
        (content_hash, content_hash)
    )
    return row[0] if row else None
```

If a duplicate is found, create a symlink or copy the existing `.md` instead of re-converting. Log it:
```python
logger.info("duplicate_skipped", member_path=member_path, duplicate_of=existing_output)
```

---

## 3. Archive Handler Architecture

### 3.1 Base class: `core/handlers/archive_base.py`

```python
"""
Base class for all archive format handlers.

All archive handlers inherit from this. The base class provides:
- Temp directory lifecycle management (create on enter, destroy on exit)
- Recursive extraction with depth tracking
- Zip-bomb protection (max decompressed size)
- Password attempt logic
- Member enumeration and metadata collection
- Delegation to the format registry for inner file conversion
"""

import hashlib
import os
import shutil
import tempfile
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

# Safety limits
MAX_NESTING_DEPTH = int(os.environ.get("ARCHIVE_MAX_DEPTH", "20"))
MAX_DECOMPRESSED_BYTES = int(os.environ.get("ARCHIVE_MAX_SIZE_GB", "50")) * 1024 * 1024 * 1024
PASSWORD_FILE_PATH = os.environ.get("ARCHIVE_PASSWORD_FILE", "config/archive_passwords.txt")


@dataclass
class ArchiveMember:
    """Metadata for a single file inside an archive."""
    path: str                       # path inside the archive
    size: int                       # uncompressed size in bytes
    modified_at: Optional[datetime] # mtime from archive metadata
    is_directory: bool
    is_archive: bool               # True if this member is itself an archive format
    content_hash: Optional[str] = None  # populated after extraction


@dataclass
class ArchiveManifest:
    """Summary of an archive's contents, used to generate the summary .md."""
    archive_path: str
    archive_size: int               # size of the archive file itself
    archive_modified_at: str        # mtime of the archive file (ISO 8601)
    archive_hash: str               # SHA-256 of the archive file
    format: str                     # zip, tar.gz, 7z, rar, cab, iso
    member_count: int
    total_uncompressed_size: int
    members: list[ArchiveMember] = field(default_factory=list)
    password_protected: bool = False
    password_used: Optional[str] = None  # which password worked (do NOT log the actual password)
    errors: list[str] = field(default_factory=list)


def load_passwords() -> list[str]:
    """Load passwords from the user-configurable password file."""
    passwords = [""]  # Always try empty password first
    try:
        pw_path = Path(PASSWORD_FILE_PATH)
        if pw_path.exists():
            with open(pw_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        passwords.append(line)
            logger.info("archive_passwords_loaded", count=len(passwords), path=str(pw_path))
        else:
            logger.warning("archive_password_file_not_found", path=str(pw_path))
    except Exception as e:
        logger.error("archive_password_file_error", error=str(e), path=str(PASSWORD_FILE_PATH))
    return passwords


def compute_file_hash(file_path: str | Path) -> str:
    """Compute SHA-256 hash of a file. Reads in 64KB chunks for memory efficiency."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


class ArchiveHandler:
    """
    Base class for archive format handlers.
    
    Subclasses must implement:
    - can_handle(path) -> bool
    - list_members(path, password) -> list[ArchiveMember]
    - extract_member(path, member, dest_dir, password) -> Path
    - detect_password_protected(path) -> bool
    """

    format_name: str = "unknown"
    extensions: list[str] = []

    def __init__(self):
        self._passwords = load_passwords()
        self._total_extracted_bytes = 0

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Return True if this handler can process the given file."""
        ...

    @abstractmethod
    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        """List all members in the archive without extracting."""
        ...

    @abstractmethod
    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path, password: Optional[str] = None) -> Path:
        """Extract a single member to dest_dir. Returns path to extracted file."""
        ...

    @abstractmethod
    def detect_password_protected(self, path: Path) -> bool:
        """Return True if the archive is password-protected."""
        ...

    def find_working_password(self, path: Path) -> Optional[str]:
        """Try each password from the list. Returns the first one that works, or None."""
        if not self.detect_password_protected(path):
            return ""  # Not password-protected, empty string means "no password needed"
        
        for pw in self._passwords:
            try:
                # Try listing members with this password — if it works, the password is correct
                self.list_members(path, password=pw)
                logger.info("archive_password_found", archive=str(path), 
                           password_index=self._passwords.index(pw))  # Log index, NOT the password
                return pw
            except Exception:
                continue
        
        logger.warning("archive_password_exhausted", archive=str(path),
                       passwords_tried=len(self._passwords))
        return None

    def check_decompression_limit(self, additional_bytes: int) -> bool:
        """Returns True if extracting additional_bytes would exceed the limit."""
        if self._total_extracted_bytes + additional_bytes > MAX_DECOMPRESSED_BYTES:
            logger.error("archive_decompression_limit_exceeded",
                        current_bytes=self._total_extracted_bytes,
                        additional_bytes=additional_bytes,
                        limit_bytes=MAX_DECOMPRESSED_BYTES)
            return True
        return False

    def track_extracted_bytes(self, byte_count: int):
        """Track cumulative extracted bytes for zip-bomb protection."""
        self._total_extracted_bytes += byte_count

    async def process_archive(
        self,
        archive_path: Path,
        output_dir: Path,
        db,
        archive_file_id: int,
        convert_fn,          # async function: (file_path, output_dir) -> output_path
        nesting_depth: int = 0,
        parent_temp_dir: Optional[Path] = None,
    ) -> ArchiveManifest:
        """
        Main entry point. Extracts, converts, and cleans up.
        
        Args:
            archive_path: Path to the archive file
            output_dir: Where to write converted .md files
            db: Database connection
            archive_file_id: Row ID of this archive in the main file tracking table
            convert_fn: Async callable that converts a single file through the pipeline
            nesting_depth: Current recursion depth (0 = top-level)
            parent_temp_dir: If nested, the parent's temp dir (for cleanup tracking)
        """
        if nesting_depth > MAX_NESTING_DEPTH:
            logger.error("archive_max_depth_exceeded", archive=str(archive_path),
                        depth=nesting_depth, max_depth=MAX_NESTING_DEPTH)
            return ArchiveManifest(
                archive_path=str(archive_path),
                archive_size=archive_path.stat().st_size,
                archive_modified_at=datetime.fromtimestamp(archive_path.stat().st_mtime).isoformat(),
                archive_hash=compute_file_hash(archive_path),
                format=self.format_name,
                member_count=0,
                total_uncompressed_size=0,
                errors=[f"Max nesting depth ({MAX_NESTING_DEPTH}) exceeded"]
            )

        # Create per-archive temp directory
        temp_dir = Path(tempfile.mkdtemp(prefix=f"markflow_archive_{nesting_depth}_"))
        logger.info("archive_processing_start", archive=str(archive_path),
                    format=self.format_name, depth=nesting_depth, temp_dir=str(temp_dir))

        try:
            # Compute archive-level metadata
            stat = archive_path.stat()
            manifest = ArchiveManifest(
                archive_path=str(archive_path),
                archive_size=stat.st_size,
                archive_modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                archive_hash=compute_file_hash(archive_path),
                format=self.format_name,
                member_count=0,
                total_uncompressed_size=0,
            )

            # Try passwords if needed
            password = self.find_working_password(archive_path)
            if password is None:
                manifest.password_protected = True
                manifest.errors.append("Password-protected archive: all passwords exhausted")
                # Still generate summary .md with what we know
                await self._write_summary_md(manifest, output_dir, archive_path)
                return manifest

            if password != "":
                manifest.password_protected = True
                manifest.password_used = "(password #%d)" % self._passwords.index(password)

            # List members
            try:
                members = self.list_members(archive_path, password=password)
            except Exception as e:
                manifest.errors.append(f"Failed to list archive contents: {e}")
                logger.error("archive_list_failed", archive=str(archive_path), error=str(e))
                await self._write_summary_md(manifest, output_dir, archive_path)
                return manifest

            manifest.members = members
            manifest.member_count = len([m for m in members if not m.is_directory])
            manifest.total_uncompressed_size = sum(m.size for m in members if not m.is_directory)

            # Check decompression limit
            if self.check_decompression_limit(manifest.total_uncompressed_size):
                manifest.errors.append(
                    f"Archive uncompressed size ({manifest.total_uncompressed_size} bytes) "
                    f"would exceed limit ({MAX_DECOMPRESSED_BYTES} bytes). Skipped."
                )
                await self._write_summary_md(manifest, output_dir, archive_path)
                return manifest

            # Extract and process each member
            for member in members:
                if member.is_directory:
                    continue

                try:
                    # Extract single member
                    extracted_path = self.extract_member(archive_path, member, temp_dir, password=password)
                    self.track_extracted_bytes(member.size)

                    # Compute content hash
                    member.content_hash = compute_file_hash(extracted_path)

                    # Record in archive_members table
                    member_id = await self._record_member(
                        db, archive_file_id, member, nesting_depth
                    )

                    # Check for duplicate by content hash
                    from core.handlers.archive_base import compute_file_hash  # avoid circular
                    duplicate_output = await self._find_duplicate(db, member.content_hash)
                    if duplicate_output:
                        await self._update_member_status(
                            db, member_id, "duplicate", output_path=duplicate_output
                        )
                        logger.info("archive_member_duplicate_skipped",
                                   member=member.path, duplicate_of=duplicate_output)
                        continue

                    # Check if this member is itself an archive (nested)
                    if member.is_archive and nesting_depth < MAX_NESTING_DEPTH:
                        # Recursive: get the appropriate handler and process
                        from core.handlers.archive_registry import get_archive_handler
                        nested_handler = get_archive_handler(extracted_path)
                        if nested_handler:
                            nested_manifest = await nested_handler.process_archive(
                                archive_path=extracted_path,
                                output_dir=output_dir,
                                db=db,
                                archive_file_id=archive_file_id,
                                convert_fn=convert_fn,
                                nesting_depth=nesting_depth + 1,
                                parent_temp_dir=temp_dir,
                            )
                            await self._update_member_status(db, member_id, "converted")
                            continue

                    # Convert through the normal pipeline
                    try:
                        output_path = await convert_fn(extracted_path, output_dir)
                        await self._update_member_status(
                            db, member_id, "converted", output_path=str(output_path)
                        )
                    except Exception as e:
                        await self._update_member_status(
                            db, member_id, "error", error_message=str(e)
                        )
                        manifest.errors.append(f"{member.path}: {e}")
                        logger.error("archive_member_conversion_failed",
                                    member=member.path, error=str(e))

                except Exception as e:
                    manifest.errors.append(f"{member.path}: extraction failed: {e}")
                    logger.error("archive_member_extract_failed",
                                member=member.path, error=str(e))

            # Generate summary .md
            await self._write_summary_md(manifest, output_dir, archive_path)

            logger.info("archive_processing_complete", archive=str(archive_path),
                       members_processed=manifest.member_count,
                       errors=len(manifest.errors))

            return manifest

        finally:
            # CRITICAL: Clean up temp directory immediately
            # This is in a finally block so it runs even if processing crashes
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info("archive_temp_cleaned", temp_dir=str(temp_dir))
            except Exception as e:
                logger.error("archive_temp_cleanup_failed", temp_dir=str(temp_dir), error=str(e))

    async def _write_summary_md(self, manifest: ArchiveManifest, output_dir: Path, archive_path: Path):
        """Generate the summary .md file for this archive."""
        # Output path mirrors source hierarchy: archive.zip -> archive.zip.md (summary)
        archive_name = archive_path.name
        summary_path = output_dir / f"{archive_name}.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# Archive: {archive_name}",
            "",
            "| Property | Value |",
            "|----------|-------|",
            f"| Format | {manifest.format} |",
            f"| Archive Size | {self._human_size(manifest.archive_size)} |",
            f"| Modified | {manifest.archive_modified_at} |",
            f"| SHA-256 | `{manifest.archive_hash}` |",
            f"| Files | {manifest.member_count} |",
            f"| Total Uncompressed | {self._human_size(manifest.total_uncompressed_size)} |",
            f"| Password Protected | {'Yes' if manifest.password_protected else 'No'} |",
            "",
        ]

        if manifest.errors:
            lines.append("## Errors")
            lines.append("")
            for err in manifest.errors:
                lines.append(f"- {err}")
            lines.append("")

        if manifest.members:
            lines.append("## Contents")
            lines.append("")
            lines.append("| File | Size | Modified | Type |")
            lines.append("|------|------|----------|------|")
            for m in sorted(manifest.members, key=lambda x: x.path):
                if m.is_directory:
                    continue
                ext = Path(m.path).suffix.lower()
                mtime = m.modified_at.isoformat() if m.modified_at else "—"
                lines.append(
                    f"| `{m.path}` | {self._human_size(m.size)} | {mtime} | {ext or '—'} |"
                )
            lines.append("")

        # Write atomically (temp file + rename)
        import tempfile as tf
        tmp_fd, tmp_path = tf.mkstemp(dir=summary_path.parent, suffix=".md.tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            os.replace(tmp_path, summary_path)
        except Exception:
            os.unlink(tmp_path)
            raise

    async def _record_member(self, db, archive_file_id: int, member: ArchiveMember, depth: int) -> int:
        """Insert a row into archive_members. Returns the new row ID."""
        result = await db.execute(
            """INSERT INTO archive_members 
               (archive_file_id, member_path, member_size, member_modified_at, 
                member_hash, status, is_archive, nesting_depth)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                archive_file_id,
                member.path,
                member.size,
                member.modified_at.isoformat() if member.modified_at else None,
                member.content_hash,
                1 if member.is_archive else 0,
                depth + 1,
            )
        )
        await db.commit()
        return result.lastrowid

    async def _update_member_status(self, db, member_id: int, status: str,
                                      output_path: str = None, error_message: str = None):
        """Update an archive_members row with conversion result."""
        await db.execute(
            """UPDATE archive_members 
               SET status = ?, output_path = ?, error_message = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (status, output_path, error_message, member_id)
        )
        await db.commit()

    async def _find_duplicate(self, db, content_hash: str) -> Optional[str]:
        """Check if a file with this content hash has already been converted."""
        # Check archive_members first
        row = await db.execute_fetchone(
            """SELECT output_path FROM archive_members 
               WHERE member_hash = ? AND status = 'converted' AND output_path IS NOT NULL
               LIMIT 1""",
            (content_hash,)
        )
        if row:
            return row[0]
        
        # Also check the main file tracking table (file might exist outside any archive)
        # IMPORTANT: Replace <existing_table> and column names with actual names from CLAUDE.md
        # This query may need adjustment based on the actual schema
        try:
            row = await db.execute_fetchone(
                """SELECT output_path FROM bulk_files
                   WHERE content_hash = ? AND status = 'success' AND output_path IS NOT NULL
                   LIMIT 1""",
                (content_hash,)
            )
            if row:
                return row[0]
        except Exception:
            pass  # Table or column might not exist yet — non-fatal
        
        return None

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Convert bytes to human-readable string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
```

### 3.2 Individual format handlers

Create each handler as a separate file under `core/handlers/`. Every handler subclasses `ArchiveHandler` and implements the four abstract methods.

#### `core/handlers/archive_zip.py`

```python
"""Handler for .zip archives."""
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler, ArchiveMember, ARCHIVE_EXTENSIONS

class ZipArchiveHandler(ArchiveHandler):
    format_name = "zip"
    extensions = [".zip"]

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".zip" and zipfile.is_zipfile(path)

    def detect_password_protected(self, path: Path) -> bool:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for info in zf.infolist():
                    if info.flag_bits & 0x1:  # Bit 0 = encrypted
                        return True
            return False
        except Exception:
            return False

    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        pw_bytes = password.encode("utf-8") if password else None
        members = []
        with zipfile.ZipFile(path, "r") as zf:
            if pw_bytes:
                zf.setpassword(pw_bytes)
            for info in zf.infolist():
                # Test extraction if password-protected (validates password)
                if pw_bytes and info.flag_bits & 0x1:
                    zf.read(info.filename, pwd=pw_bytes)  # Will raise BadZipFile if wrong password
                    # Only read first member to test password, then break this test
                    # (actual list_members just catalogs, doesn't need to read all)
                
                is_dir = info.is_dir()
                mtime = datetime(*info.date_time) if info.date_time else None
                ext = Path(info.filename).suffix.lower()
                members.append(ArchiveMember(
                    path=info.filename,
                    size=info.file_size,
                    modified_at=mtime,
                    is_directory=is_dir,
                    is_archive=ext in ARCHIVE_EXTENSIONS,
                ))
        return members

    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path,
                       password: Optional[str] = None) -> Path:
        pw_bytes = password.encode("utf-8") if password else None
        with zipfile.ZipFile(path, "r") as zf:
            zf.extract(member.path, path=dest_dir, pwd=pw_bytes)
        return dest_dir / member.path
```

#### `core/handlers/archive_tar.py`

```python
"""Handler for .tar, .tar.gz, .tar.bz2, .tar.xz archives."""
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler, ArchiveMember, ARCHIVE_EXTENSIONS

class TarArchiveHandler(ArchiveHandler):
    format_name = "tar"
    extensions = [".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"]

    def can_handle(self, path: Path) -> bool:
        name = path.name.lower()
        return any(name.endswith(ext) for ext in self.extensions) and tarfile.is_tarfile(path)

    def detect_password_protected(self, path: Path) -> bool:
        return False  # tar archives are never password-protected (compression might be, but tar itself isn't)

    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        members = []
        with tarfile.open(path, "r:*") as tf:
            for info in tf.getmembers():
                ext = Path(info.name).suffix.lower()
                members.append(ArchiveMember(
                    path=info.name,
                    size=info.size,
                    modified_at=datetime.fromtimestamp(info.mtime) if info.mtime else None,
                    is_directory=info.isdir(),
                    is_archive=ext in ARCHIVE_EXTENSIONS,
                ))
        return members

    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path,
                       password: Optional[str] = None) -> Path:
        with tarfile.open(path, "r:*") as tf:
            # Security: prevent path traversal
            member_info = tf.getmember(member.path)
            if member_info.name.startswith("/") or ".." in member_info.name:
                raise ValueError(f"Unsafe path in tar archive: {member_info.name}")
            tf.extract(member_info, path=dest_dir, filter="data")
        return dest_dir / member.path
```

#### `core/handlers/archive_7z.py`

```python
"""Handler for .7z archives."""
import py7zr
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler, ArchiveMember, ARCHIVE_EXTENSIONS

class SevenZipArchiveHandler(ArchiveHandler):
    format_name = "7z"
    extensions = [".7z"]

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".7z"

    def detect_password_protected(self, path: Path) -> bool:
        try:
            with py7zr.SevenZipFile(path, "r") as zf:
                return zf.needs_password()
        except Exception:
            return True  # If we can't even open it, assume password-protected

    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        members = []
        kwargs = {"password": password} if password else {}
        with py7zr.SevenZipFile(path, "r", **kwargs) as zf:
            for info in zf.list():
                ext = Path(info.filename).suffix.lower()
                members.append(ArchiveMember(
                    path=info.filename,
                    size=info.uncompressed if hasattr(info, 'uncompressed') else 0,
                    modified_at=info.creationtime if hasattr(info, 'creationtime') else None,
                    is_directory=info.is_directory,
                    is_archive=ext in ARCHIVE_EXTENSIONS,
                ))
        return members

    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path,
                       password: Optional[str] = None) -> Path:
        kwargs = {"password": password} if password else {}
        with py7zr.SevenZipFile(path, "r", **kwargs) as zf:
            zf.extract(path=dest_dir, targets=[member.path])
        return dest_dir / member.path
```

#### `core/handlers/archive_rar.py`

```python
"""Handler for .rar archives."""
import rarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler, ArchiveMember, ARCHIVE_EXTENSIONS

class RarArchiveHandler(ArchiveHandler):
    format_name = "rar"
    extensions = [".rar"]

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".rar" and rarfile.is_rarfile(str(path))

    def detect_password_protected(self, path: Path) -> bool:
        try:
            with rarfile.RarFile(str(path)) as rf:
                return rf.needs_password()
        except Exception:
            return True

    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        members = []
        with rarfile.RarFile(str(path)) as rf:
            if password:
                rf.setpassword(password)
            for info in rf.infolist():
                ext = Path(info.filename).suffix.lower()
                mtime = datetime(*info.date_time) if info.date_time else None
                members.append(ArchiveMember(
                    path=info.filename,
                    size=info.file_size,
                    modified_at=mtime,
                    is_directory=info.is_dir(),
                    is_archive=ext in ARCHIVE_EXTENSIONS,
                ))
        return members

    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path,
                       password: Optional[str] = None) -> Path:
        with rarfile.RarFile(str(path)) as rf:
            if password:
                rf.setpassword(password)
            rf.extract(member.path, path=str(dest_dir))
        return dest_dir / member.path
```

#### `core/handlers/archive_cab.py`

```python
"""Handler for .cab (Windows Cabinet) archives."""
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler, ArchiveMember, ARCHIVE_EXTENSIONS
import structlog

logger = structlog.get_logger()

class CabArchiveHandler(ArchiveHandler):
    """
    Cabinet files use the `cabextract` system utility.
    Install: apt-get install cabextract
    """
    format_name = "cab"
    extensions = [".cab"]

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".cab":
            return False
        # Verify cabextract is available
        try:
            subprocess.run(["cabextract", "--version"], capture_output=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning("cabextract_not_found", detail="Install cabextract for .cab support")
            return False

    def detect_password_protected(self, path: Path) -> bool:
        return False  # CAB files are not password-protected

    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        result = subprocess.run(
            ["cabextract", "-l", str(path)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"cabextract -l failed: {result.stderr}")
        
        members = []
        # Parse cabextract -l output format:
        #   Size | Date     | Time  | Name
        for line in result.stdout.splitlines():
            line = line.strip()
            # Skip header/footer lines
            if not line or line.startswith("File") or line.startswith("---") or line.startswith("All"):
                continue
            parts = line.split("|") if "|" in line else line.split()
            if len(parts) >= 4:
                try:
                    size = int(parts[0].strip())
                    name = parts[-1].strip()
                    ext = Path(name).suffix.lower()
                    members.append(ArchiveMember(
                        path=name,
                        size=size,
                        modified_at=None,  # cabextract output parsing for dates is fragile
                        is_directory=False,
                        is_archive=ext in ARCHIVE_EXTENSIONS,
                    ))
                except (ValueError, IndexError):
                    continue
        return members

    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path,
                       password: Optional[str] = None) -> Path:
        # cabextract extracts all files — filter by name using -F
        result = subprocess.run(
            ["cabextract", "-d", str(dest_dir), "-F", member.path, str(path)],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise RuntimeError(f"cabextract failed: {result.stderr}")
        return dest_dir / member.path
```

#### `core/handlers/archive_iso.py`

```python
"""Handler for .iso (ISO 9660 / UDF) disc images."""
import pycdlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler, ArchiveMember, ARCHIVE_EXTENSIONS
import structlog

logger = structlog.get_logger()

class IsoArchiveHandler(ArchiveHandler):
    format_name = "iso"
    extensions = [".iso"]

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".iso":
            return False
        try:
            iso = pycdlib.PyCdlib()
            iso.open(str(path))
            iso.close()
            return True
        except Exception:
            return False

    def detect_password_protected(self, path: Path) -> bool:
        return False  # ISO files are not password-protected

    def list_members(self, path: Path, password: Optional[str] = None) -> list[ArchiveMember]:
        members = []
        iso = pycdlib.PyCdlib()
        iso.open(str(path))
        try:
            # Try Joliet first (preserves long filenames), fall back to ISO 9660
            try:
                facade = iso.list_children(joliet_path="/")
                use_joliet = True
            except Exception:
                facade = iso.list_children(iso_path="/")
                use_joliet = False

            self._walk_iso(iso, "/", members, use_joliet)
        finally:
            iso.close()
        return members

    def _walk_iso(self, iso, dir_path: str, members: list, use_joliet: bool):
        """Recursively walk the ISO filesystem."""
        try:
            if use_joliet:
                children = list(iso.list_children(joliet_path=dir_path))
            else:
                children = list(iso.list_children(iso_path=dir_path))
        except Exception:
            return

        for child in children:
            name = child.file_identifier().decode("utf-8", errors="replace")
            if name in (".", ".."):
                continue

            child_path = f"{dir_path}/{name}".replace("//", "/")
            
            if child.is_dir():
                self._walk_iso(iso, child_path, members, use_joliet)
            else:
                ext = Path(name).suffix.lower()
                # Remove ISO 9660 version suffix (;1)
                clean_name = name.split(";")[0] if ";" in name else name
                clean_path = child_path.split(";")[0] if ";" in child_path else child_path
                
                members.append(ArchiveMember(
                    path=clean_path.lstrip("/"),
                    size=child.data_length,
                    modified_at=None,  # ISO 9660 date parsing is complex
                    is_directory=False,
                    is_archive=ext in ARCHIVE_EXTENSIONS or Path(clean_name).suffix.lower() in ARCHIVE_EXTENSIONS,
                ))

    def extract_member(self, path: Path, member: ArchiveMember, dest_dir: Path,
                       password: Optional[str] = None) -> Path:
        iso = pycdlib.PyCdlib()
        iso.open(str(path))
        try:
            output_path = dest_dir / member.path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            iso_path = "/" + member.path
            try:
                iso.get_file_from_iso(str(output_path), joliet_path=iso_path)
            except Exception:
                # Fall back to ISO 9660 path (may have ;1 suffix)
                iso.get_file_from_iso(str(output_path), iso_path=iso_path + ";1")
        finally:
            iso.close()
        return output_path
```

### 3.3 Archive registry: `core/handlers/archive_registry.py`

```python
"""
Registry of archive format handlers.

Maps file extensions to handler classes. Used by the bulk scanner and
the main format registry to route archive files to the correct handler.
"""
from pathlib import Path
from typing import Optional

from core.handlers.archive_base import ArchiveHandler
from core.handlers.archive_zip import ZipArchiveHandler
from core.handlers.archive_tar import TarArchiveHandler
from core.handlers.archive_7z import SevenZipArchiveHandler
from core.handlers.archive_rar import RarArchiveHandler
from core.handlers.archive_cab import CabArchiveHandler
from core.handlers.archive_iso import IsoArchiveHandler

# Instantiate handlers
_HANDLERS: list[ArchiveHandler] = [
    ZipArchiveHandler(),
    TarArchiveHandler(),
    SevenZipArchiveHandler(),
    RarArchiveHandler(),
    CabArchiveHandler(),
    IsoArchiveHandler(),
]

# All extensions that are considered archive formats
# Used by the member enumeration to detect nested archives
ARCHIVE_EXTENSIONS: set[str] = set()
for h in _HANDLERS:
    ARCHIVE_EXTENSIONS.update(h.extensions)

def get_archive_handler(path: Path) -> Optional[ArchiveHandler]:
    """Return the appropriate handler for the given file, or None."""
    for handler in _HANDLERS:
        if handler.can_handle(path):
            return handler
    return None

def is_archive(path: Path) -> bool:
    """Quick check: is this file extension a known archive format?"""
    name = path.name.lower()
    return any(name.endswith(ext) for ext in ARCHIVE_EXTENSIONS)
```

**IMPORTANT:** The `ARCHIVE_EXTENSIONS` set must also be importable by `archive_base.py`. Since `archive_base.py` is imported by the handlers, and `archive_registry.py` imports the handlers, there's a circular dependency. Solve this by defining `ARCHIVE_EXTENSIONS` directly in `archive_base.py` as a constant:

```python
# In archive_base.py — at module level
ARCHIVE_EXTENSIONS = {
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
    ".tar.xz", ".txz", ".7z", ".rar", ".cab", ".iso",
}
```

Then `archive_registry.py` imports it from `archive_base` rather than building it.

---

## 4. Format Registry Integration

### 4.1 Register archive extensions in the main format registry

Find the existing format registry (likely `core/format_registry.py` or similar — grep for it):

```bash
grep -rn "format_registry\|FORMAT_REGISTRY\|register_handler\|extension.*handler" core/ --include="*.py"
```

Add all archive extensions to the registry, pointing them at a single `ArchiveFormatHandler` wrapper that bridges between the format registry interface and the archive handler system:

```python
# In whatever file the format registry lives

from core.handlers.archive_registry import get_archive_handler, is_archive, ARCHIVE_EXTENSIONS

class ArchiveFormatHandler:
    """
    Bridges the format registry interface to the archive handler system.
    The format registry expects a handler with a `convert()` method.
    This wrapper delegates to the appropriate archive-specific handler.
    """
    
    async def convert(self, file_path: Path, output_dir: Path, db, file_id: int, convert_fn):
        handler = get_archive_handler(file_path)
        if not handler:
            raise ValueError(f"No archive handler found for {file_path}")
        
        manifest = await handler.process_archive(
            archive_path=file_path,
            output_dir=output_dir,
            db=db,
            archive_file_id=file_id,
            convert_fn=convert_fn,
        )
        return manifest

# Register for all archive extensions
_archive_handler = ArchiveFormatHandler()
for ext in ARCHIVE_EXTENSIONS:
    register_handler(ext, _archive_handler)
```

Adapt this to match the actual format registry API — the `register_handler` function name and `convert` method signature will be whatever the existing code uses. **Do not guess — read the existing registry code first.**

### 4.2 Bulk scanner integration

Find the bulk scanner / crawler code:

```bash
grep -rn "bulk_worker\|bulk_scanner\|scan_directory\|walk.*files" core/ --include="*.py"
```

The scanner currently walks the source directory and adds files to the processing queue. It needs to:

1. **Populate `file_size`, `modified_at`, `content_hash`** when recording a file:

```python
import os
from core.handlers.archive_base import compute_file_hash

stat = os.stat(file_path)
file_size = stat.st_size
modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
content_hash = compute_file_hash(file_path)
```

2. **Use all three fields for change detection:**

```python
async def needs_processing(db, file_path: str, file_size: int, modified_at: str, content_hash: str) -> bool:
    """Check if this file needs to be (re)processed."""
    row = await db.execute_fetchone(
        """SELECT file_size, modified_at, content_hash, status 
           FROM <existing_table> 
           WHERE file_path = ?""",
        (file_path,)
    )
    if row is None:
        return True  # New file
    
    prev_size, prev_mtime, prev_hash, prev_status = row
    
    # Quick checks first (cheap)
    if prev_status == 'error':
        return True  # Retry errors
    if prev_size != file_size or prev_mtime != modified_at:
        return True  # Size or mtime changed
    if prev_hash and prev_hash == content_hash:
        return False  # Content identical
    
    return True  # Hash mismatch or no previous hash — reprocess
```

3. **For archives: check member hashes after extracting**

When the scanner detects an archive has changed (new mtime), it re-extracts and compares member hashes against the `archive_members` table. Only members with changed hashes get re-converted. Members that haven't changed keep their existing `.md` output.

---

## 5. Dockerfile Changes

Add to the existing `apt-get install` line:

```
cabextract unrar-free p7zip-full
```

Find the line with `apt-get install -y` and append these packages. Don't create a new `RUN apt-get` line.

Add to `requirements.txt`:

```
py7zr>=0.21.0
rarfile>=4.1
pycdlib>=1.14.0
```

---

## 6. Environment Variables

Document these in `docker-compose.yml` as commented-out env vars under the markflow service:

```yaml
environment:
  # Archive processing limits
  # ARCHIVE_MAX_DEPTH: "20"           # Max nesting depth for archives-in-archives
  # ARCHIVE_MAX_SIZE_GB: "50"         # Max total decompressed size per top-level archive (GB)
  # ARCHIVE_PASSWORD_FILE: "config/archive_passwords.txt"  # Path to password list
```

---

## 7. Meilisearch Indexing

Archive summary `.md` files and individual converted member `.md` files should both be indexed in Meilisearch, exactly like any other `.md` in the output repo.

The existing Meilisearch indexing code should pick these up automatically since they're written to the output directory. **Verify** by checking how the indexer discovers files:

```bash
grep -rn "meilisearch\|index.*md\|glob.*md" core/ --include="*.py"
```

If the indexer walks the output directory for `.md` files, archive outputs will be indexed with no changes. If it only indexes files that were explicitly registered in the conversion pipeline, add archive outputs to the registration.

The summary `.md` should be indexed with these additional attributes (if the Meilisearch schema supports custom fields):
- `is_archive_summary: true`
- `archive_format: "zip"` (or tar, 7z, etc.)
- `member_count: 47`

---

## 8. Tests

### 8.1 Test fixtures

Create test archives in `tests/fixtures/archives/`:

```
tests/fixtures/archives/
├── simple.zip                # 2-3 small .txt and .docx files
├── nested.zip                # contains inner.zip which contains a .txt
├── password_protected.zip    # password: "password" (from the default list)
├── simple.tar.gz             # same content as simple.zip but tar.gz
├── simple.7z                 # same content as simple.zip but 7z
├── empty.zip                 # empty archive (zero members)
├── single_file.rar           # single .docx inside
└── has_unknown_formats.zip   # contains .exe, .dll, .dat (unconvertible files)
```

Create these with a helper script `tests/create_test_archives.py` that generates them programmatically. Run this script once; commit the resulting fixtures.

### 8.2 Test cases

Create `tests/test_archive_handlers.py`:

```python
"""Tests for archive format handlers."""

# -- Handler detection --
# test_zip_handler_detects_zip()
# test_tar_handler_detects_tar_gz()
# test_tar_handler_detects_tar_bz2()
# test_7z_handler_detects_7z()
# test_rar_handler_detects_rar()
# test_registry_returns_correct_handler()
# test_registry_returns_none_for_unknown()

# -- Member listing --
# test_zip_list_members_returns_all_files()
# test_tar_list_members_returns_all_files()
# test_member_metadata_includes_size_and_date()
# test_nested_archive_detected_as_is_archive()
# test_empty_archive_returns_empty_list()

# -- Extraction --
# test_zip_extract_single_member()
# test_tar_extract_single_member()
# test_extracted_file_matches_original_content()
# test_path_traversal_attack_blocked()

# -- Password handling --
# test_password_detection_on_protected_archive()
# test_password_found_from_list()
# test_password_exhausted_returns_none()
# test_empty_password_tried_first()
# test_password_file_loading()
# test_missing_password_file_handled_gracefully()

# -- Full pipeline --
# test_archive_process_converts_inner_docx()
# test_archive_process_generates_summary_md()
# test_summary_md_contains_member_table()
# test_nested_archive_recursive_extraction()
# test_max_depth_enforced()
# test_decompression_limit_enforced()

# -- Temp cleanup --
# test_temp_dir_removed_after_success()
# test_temp_dir_removed_after_error()
# test_temp_dir_removed_after_depth_exceeded()

# -- Deduplication --
# test_duplicate_member_skipped_by_hash()
# test_same_file_in_two_archives_deduplicated()

# -- Database --
# test_archive_members_table_created()
# test_member_recorded_with_correct_metadata()
# test_member_status_updated_after_conversion()
# test_file_size_and_hash_recorded_in_main_table()
# test_change_detection_by_size()
# test_change_detection_by_mtime()
# test_change_detection_by_hash()
# test_unchanged_file_skipped()
```

Each test function name above maps to one test. Implement all of them. Target: ~40 new tests.

### 8.3 Run tests

```bash
pytest tests/test_archive_handlers.py -v
pytest tests/ -v  # Full suite — no regressions
```

---

## 9. File Tracking Schema Update — Standalone

Even for non-archive files, the bulk scanner should now track `file_size`, `content_hash`, and `modified_at`. This means updating the scanner's "record a file" code path to compute and store these values for EVERY file, not just archives.

**This is a schema migration**, so:
1. Add the columns via ALTER TABLE (with try/except as shown in section 2.2)
2. Update the scanner's INSERT/UPDATE statements to include the new columns
3. Update the change detection query (section 4.2) to use all three fields
4. Backfill: for existing records without these columns, the next scan pass will compute and fill them

---

## 10. Security Considerations

### 10.1 Path traversal

Archive members can contain paths like `../../etc/passwd`. Every extraction must sanitize paths:

```python
def safe_extract_path(member_path: str, dest_dir: Path) -> Path:
    """Resolve the extraction path and verify it stays within dest_dir."""
    # Normalize and resolve
    target = (dest_dir / member_path).resolve()
    dest_resolved = dest_dir.resolve()
    
    # Verify the target is within the destination directory
    if not str(target).startswith(str(dest_resolved)):
        raise ValueError(f"Path traversal detected: {member_path}")
    
    return target
```

Call this in every handler's `extract_member` method before writing.

### 10.2 Symlink attacks

Some archive formats support symlinks. Never follow symlinks during extraction:
- `tarfile`: use `filter="data"` (already in the tar handler above)
- `zipfile`: check for symlink flag before extracting
- `py7zr`: does not support symlinks (safe)

### 10.3 Filename sanitization

Archive member names can contain characters illegal on Windows (`:`, `*`, `?`, `"`, etc.). Sanitize output filenames:

```python
import re

def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are illegal on Windows filesystems."""
    # Replace illegal chars with underscore
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # Remove trailing dots and spaces (Windows doesn't allow them)
    sanitized = sanitized.rstrip('. ')
    return sanitized or '_'
```

---

## 11. Summary of All Files to Create or Modify

### New files:
| File | Purpose |
|------|---------|
| `core/handlers/archive_base.py` | Base class, temp management, password logic, manifest, hash util |
| `core/handlers/archive_zip.py` | .zip handler |
| `core/handlers/archive_tar.py` | .tar/.tar.gz/.tar.bz2/.tar.xz handler |
| `core/handlers/archive_7z.py` | .7z handler |
| `core/handlers/archive_rar.py` | .rar handler |
| `core/handlers/archive_cab.py` | .cab handler |
| `core/handlers/archive_iso.py` | .iso handler |
| `core/handlers/archive_registry.py` | Extension-to-handler lookup + ARCHIVE_EXTENSIONS |
| `config/archive_passwords.txt` | Default password list |
| `tests/test_archive_handlers.py` | ~40 tests |
| `tests/create_test_archives.py` | Script to generate test fixtures |

### Modified files:
| File | Change |
|------|--------|
| `requirements.txt` | Add py7zr, rarfile, pycdlib |
| `Dockerfile` | Add cabextract, unrar-free, p7zip-full to apt-get |
| `docker-compose.yml` | Document ARCHIVE_* env vars, ensure config/ volume mount |
| Format registry file (find it) | Register archive extensions |
| Bulk scanner file (find it) | Add file_size/hash/mtime tracking + archive routing |
| DB migration/setup file (find it) | Add columns + archive_members table |
| `CLAUDE.md` | Version bump + document everything |

---

## 12. CLAUDE.md Update

After all tests pass, update CLAUDE.md:

- Bump version
- Under completed work, add:
  - `Archive scanning: .zip, .tar.gz, .tar.bz2, .tar.xz, .7z, .rar, .cab, .iso`
  - `Archive pipeline: full extraction + conversion of inner files, summary .md per archive`
  - `Recursive archives: up to 20 levels deep, zip-bomb protection at 50GB default`
  - `Password-protected archives: tries passwords from config/archive_passwords.txt`
  - `File tracking: file_size, modified_at, content_hash (SHA-256) on all files`
  - `Archive member tracking: archive_members table with per-member hash deduplication`
  - `Temp cleanup: per-archive temp dir, wiped in finally block after processing`
- Under architecture patterns, add:
  - `Archive handlers: core/handlers/archive_*.py, all inherit ArchiveHandler base class`
  - `Archive registry: core/handlers/archive_registry.py — maps extensions to handlers`
  - `ARCHIVE_EXTENSIONS defined in archive_base.py to avoid circular imports`
  - `Password file: config/archive_passwords.txt — one password per line, # for comments`
- Under environment variables, add:
  - `ARCHIVE_MAX_DEPTH (default 20)`
  - `ARCHIVE_MAX_SIZE_GB (default 50)`
  - `ARCHIVE_PASSWORD_FILE (default config/archive_passwords.txt)`
- Under gotchas/learnings, add:
  - `Archive path traversal: always use safe_extract_path() — never trust member paths from archives`
  - `Tar symlinks: always use filter="data" with tarfile.extract()`
  - `Circular import: ARCHIVE_EXTENSIONS lives in archive_base.py, not archive_registry.py`
  - `CAB files: require cabextract system binary — handler degrades gracefully if missing`
  - `ISO files: pycdlib — try Joliet first for long filenames, fall back to ISO 9660`
