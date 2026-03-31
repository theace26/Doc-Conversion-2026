"""
Archive format handler — .zip, .tar, .tar.gz, .7z, .rar, .cab, .iso.

Ingest:
  Extracts archive contents to a per-archive temp directory, enumerates all
  members, and recursively converts each convertible file through the format
  registry (depth-limited to 20 levels for nested archives).

  Produces a DocumentModel with:
    - Summary table (archive metadata, member listing)
    - Converted content for each inner file as subsections

  Password-protected archives — full cracking cascade:
    1. Empty string + archive password file + session-found passwords
    2. Dictionary attack (common.txt wordlist + mutations)
    3. Brute-force (configurable charset/length/timeout from user preferences)
  Successful passwords are saved back to the file and reused across the session.
  Zip-bomb protection: per-entry ratio check, total size cap, quine detection.

Export:
  Not supported — archives are ingest-only.
"""

import hashlib
import io
import itertools
import os
import shutil
import string
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from core.archive_safety import (
    ARCHIVE_EXTENSIONS,
    ExtractionTracker,
    MAX_NESTING_DEPTH,
    check_compression_ratio,
    check_entry_count,
    check_nesting_depth,
)
from core.storage_probe import ErrorRateMonitor
from core.document_model import (
    DocumentMetadata,
    DocumentModel,
    Element,
    ElementType,
)
from formats.base import FormatHandler, get_handler, register_handler

log = structlog.get_logger(__name__)

_PASSWORD_FILE = os.environ.get("ARCHIVE_PASSWORD_FILE", "config/archive_passwords.txt")
_WORDLIST_DIR = Path(__file__).parent.parent / "core" / "password_wordlists"

# Session-level password reuse: passwords that worked during this process lifetime
# are tried first on subsequent archives. Thread-safe via lock.
_found_passwords: set[str] = set()
_password_lock = threading.Lock()


def _load_passwords() -> list[str]:
    """Load passwords: found passwords first, then static file, always try empty first."""
    passwords = [""]  # Always try empty password first

    # Found passwords from this session go right after empty (most likely to work)
    with _password_lock:
        for pw in _found_passwords:
            if pw and pw not in passwords:
                passwords.append(pw)

    # Then the static file
    try:
        pw_path = Path(_PASSWORD_FILE)
        if pw_path.exists():
            for line in pw_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and line not in passwords:
                    passwords.append(line)
    except Exception as exc:
        log.warning("archive_password_file_error", error=str(exc))
    return passwords


def _save_found_password(password: str) -> None:
    """Persist a successful password to session memory and the password file."""
    if not password:
        return

    # Add to session set
    with _password_lock:
        if password in _found_passwords:
            return  # Already known
        _found_passwords.add(password)

    # Append to the password file (if not already present)
    try:
        pw_path = Path(_PASSWORD_FILE)
        existing = set()
        if pw_path.exists():
            for line in pw_path.read_text(encoding="utf-8").splitlines():
                existing.add(line.strip())

        if password not in existing:
            pw_path.parent.mkdir(parents=True, exist_ok=True)
            with open(pw_path, "a", encoding="utf-8") as f:
                f.write(f"\n{password}\n")
            log.info("archive_password_saved",
                     password_count=len(existing) + 1)
    except Exception as exc:
        log.warning("archive_password_save_failed", error=str(exc))


def _load_dictionary() -> list[str]:
    """Load the bundled common password dictionary."""
    dict_file = _WORDLIST_DIR / "common.txt"
    if not dict_file.exists():
        return []
    try:
        lines = dict_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        return [line.strip() for line in lines if line.strip()]
    except Exception:
        return []


def _mutations(password: str) -> list[str]:
    """Generate common password mutations."""
    if not password:
        return []
    return [
        password.capitalize(),
        password.upper(),
        password + "1",
        password + "!",
        password + "123",
        password + "2024",
        password + "2025",
        password + "2026",
    ]


# Full ASCII charset: all bytes 0x01–0x7F (excludes only NULL which breaks C-string libs)
_ALL_ASCII = "".join(chr(i) for i in range(1, 128))


def _get_charset(charset_name: str) -> str:
    """Get character set for brute-force based on config name.

    Charsets (from narrowest to widest):
      numeric:       0-9 (10 chars)
      alpha:         a-z (26 chars)
      alphanumeric:  a-z + 0-9 (36 chars)
      all_printable: letters + digits + punctuation + space (95 chars)
      all_ascii:     every ASCII byte 0x01-0x7F including control chars (127 chars)

    Default is all_ascii for maximum coverage on company archives.
    """
    if charset_name == "numeric":
        return string.digits
    elif charset_name == "alpha":
        return string.ascii_lowercase
    elif charset_name == "alphanumeric":
        return string.ascii_lowercase + string.digits
    elif charset_name == "all_printable":
        return string.ascii_letters + string.digits + string.punctuation + " "
    elif charset_name == "all_ascii":
        return _ALL_ASCII
    return _ALL_ASCII


def _compute_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file in 64KB chunks."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def _human_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _is_compound_tar(file_path: Path) -> bool:
    """Check if file is a compound tar extension (.tar.gz, .tar.bz2, .tar.xz)."""
    name = file_path.name.lower()
    return any(name.endswith(ext) for ext in (".tar.gz", ".tar.bz2", ".tar.xz"))


def _get_archive_format(file_path: Path) -> str:
    """Determine archive format label from path."""
    name = file_path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        return "tar.gz"
    if name.endswith((".tar.bz2", ".tbz2")):
        return "tar.bz2"
    if name.endswith((".tar.xz", ".txz")):
        return "tar.xz"
    if name.endswith(".tar"):
        return "tar"
    return file_path.suffix.lower().lstrip(".")


# ── Member dataclass ─────────────────────────────────────────────────────────

@dataclass
class _ArchiveMember:
    path: str
    size: int = 0
    modified_at: datetime | None = None
    is_directory: bool = False

    @property
    def ext(self) -> str:
        return Path(self.path).suffix.lower()

    @property
    def is_archive(self) -> bool:
        name = Path(self.path).name.lower()
        return any(name.endswith(e) for e in ARCHIVE_EXTENSIONS)


# ── Format-specific extractors ───────────────────────────────────────────────

def _list_zip(path: Path, password: str | None) -> list[_ArchiveMember]:
    import zipfile
    pw = password.encode("utf-8") if password else None
    members = []
    with zipfile.ZipFile(path, "r") as zf:
        if pw:
            zf.setpassword(pw)
        for info in zf.infolist():
            mtime = datetime(*info.date_time) if info.date_time else None
            members.append(_ArchiveMember(
                path=info.filename, size=info.file_size,
                modified_at=mtime, is_directory=info.is_dir(),
            ))
    return members


def _extract_zip(path: Path, member: _ArchiveMember, dest: Path, password: str | None) -> Path:
    import zipfile
    pw = password.encode("utf-8") if password else None
    with zipfile.ZipFile(path, "r") as zf:
        zf.extract(member.path, path=dest, pwd=pw)
    return dest / member.path


def _is_zip_encrypted(path: Path) -> bool:
    import zipfile
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return any(info.flag_bits & 0x1 for info in zf.infolist())
    except Exception:
        return False


def _list_tar(path: Path, password: str | None) -> list[_ArchiveMember]:
    import tarfile
    members = []
    with tarfile.open(path, "r:*") as tf:
        for info in tf.getmembers():
            mtime = datetime.fromtimestamp(info.mtime) if info.mtime else None
            members.append(_ArchiveMember(
                path=info.name, size=info.size,
                modified_at=mtime, is_directory=info.isdir(),
            ))
    return members


def _extract_tar(path: Path, member: _ArchiveMember, dest: Path, password: str | None) -> Path:
    import tarfile
    with tarfile.open(path, "r:*") as tf:
        info = tf.getmember(member.path)
        if info.name.startswith("/") or ".." in info.name:
            raise ValueError(f"Unsafe path in tar: {info.name}")
        tf.extract(info, path=dest, filter="data")
    return dest / member.path


def _list_7z(path: Path, password: str | None) -> list[_ArchiveMember]:
    import py7zr
    kwargs = {"password": password} if password else {}
    members = []
    with py7zr.SevenZipFile(path, "r", **kwargs) as zf:
        for info in zf.list():
            members.append(_ArchiveMember(
                path=info.filename,
                size=getattr(info, "uncompressed", 0) or 0,
                modified_at=getattr(info, "creationtime", None),
                is_directory=info.is_directory,
            ))
    return members


def _extract_7z(path: Path, member: _ArchiveMember, dest: Path, password: str | None) -> Path:
    import py7zr
    kwargs = {"password": password} if password else {}
    with py7zr.SevenZipFile(path, "r", **kwargs) as zf:
        zf.extract(path=dest, targets=[member.path])
    return dest / member.path


def _is_7z_encrypted(path: Path) -> bool:
    try:
        import py7zr
        with py7zr.SevenZipFile(path, "r") as zf:
            return zf.needs_password()
    except Exception:
        return True


def _list_rar(path: Path, password: str | None) -> list[_ArchiveMember]:
    import rarfile
    members = []
    with rarfile.RarFile(str(path)) as rf:
        if password:
            rf.setpassword(password)
        for info in rf.infolist():
            mtime = datetime(*info.date_time) if info.date_time else None
            members.append(_ArchiveMember(
                path=info.filename, size=info.file_size,
                modified_at=mtime, is_directory=info.is_dir(),
            ))
    return members


def _extract_rar(path: Path, member: _ArchiveMember, dest: Path, password: str | None) -> Path:
    import rarfile
    with rarfile.RarFile(str(path)) as rf:
        if password:
            rf.setpassword(password)
        rf.extract(member.path, path=str(dest))
    return dest / member.path


def _is_rar_encrypted(path: Path) -> bool:
    try:
        import rarfile
        with rarfile.RarFile(str(path)) as rf:
            return rf.needs_password()
    except Exception:
        return True


def _list_iso(path: Path, password: str | None) -> list[_ArchiveMember]:
    import pycdlib
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    members: list[_ArchiveMember] = []
    try:
        _walk_iso(iso, "/", members)
    finally:
        iso.close()
    return members


def _walk_iso(iso, dir_path: str, members: list[_ArchiveMember], use_joliet: bool = True):
    """Recursively walk an ISO filesystem."""
    try:
        if use_joliet:
            children = list(iso.list_children(joliet_path=dir_path))
        else:
            children = list(iso.list_children(iso_path=dir_path))
    except Exception:
        if use_joliet:
            _walk_iso(iso, dir_path, members, use_joliet=False)
        return

    for child in children:
        name = child.file_identifier().decode("utf-8", errors="replace")
        if name in (".", ".."):
            continue
        child_path = f"{dir_path}/{name}".replace("//", "/")
        if child.is_dir():
            _walk_iso(iso, child_path, members, use_joliet)
        else:
            clean = name.split(";")[0]
            clean_path = child_path.split(";")[0].lstrip("/")
            members.append(_ArchiveMember(
                path=clean_path, size=child.data_length,
                is_directory=False,
            ))


def _extract_iso(path: Path, member: _ArchiveMember, dest: Path, password: str | None) -> Path:
    import pycdlib
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        output = dest / member.path
        output.parent.mkdir(parents=True, exist_ok=True)
        iso_path = "/" + member.path
        try:
            iso.get_file_from_iso(str(output), joliet_path=iso_path)
        except Exception:
            iso.get_file_from_iso(str(output), iso_path=iso_path + ";1")
    finally:
        iso.close()
    return output


def _list_cab(path: Path, password: str | None) -> list[_ArchiveMember]:
    import subprocess
    result = subprocess.run(
        ["cabextract", "-l", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cabextract -l failed: {result.stderr.strip()}")
    members = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("File") or line.startswith("---") or line.startswith("All"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                size = int(parts[0])
                name = parts[-1]
                members.append(_ArchiveMember(path=name, size=size))
            except (ValueError, IndexError):
                continue
    return members


def _extract_cab(path: Path, member: _ArchiveMember, dest: Path, password: str | None) -> Path:
    import subprocess
    result = subprocess.run(
        ["cabextract", "-d", str(dest), "-F", member.path, str(path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cabextract failed: {result.stderr.strip()}")
    return dest / member.path


# ── Batch extraction functions ────────────────────────────────────────────────
# These extract all members at once — one archive open/parse cycle instead of N.
# Much faster over NAS (one network read) and HDD (one sequential pass).

def _batch_extract_zip(path: Path, dest: Path, password: str | None) -> None:
    import zipfile
    pw = password.encode("utf-8") if password else None
    with zipfile.ZipFile(path, "r") as zf:
        if pw:
            zf.setpassword(pw)
        zf.extractall(path=dest, pwd=pw)


def _batch_extract_tar(path: Path, dest: Path, password: str | None) -> None:
    import tarfile
    with tarfile.open(path, "r:*") as tf:
        # Filter out unsafe paths
        safe_members = []
        for info in tf.getmembers():
            if info.name.startswith("/") or ".." in info.name:
                log.warning("tar_unsafe_path_skipped", path=info.name)
                continue
            safe_members.append(info)
        tf.extractall(path=dest, members=safe_members, filter="data")


def _batch_extract_7z(path: Path, dest: Path, password: str | None) -> None:
    import py7zr
    kwargs = {"password": password} if password else {}
    with py7zr.SevenZipFile(path, "r", **kwargs) as zf:
        zf.extractall(path=dest)


def _batch_extract_rar(path: Path, dest: Path, password: str | None) -> None:
    import rarfile
    with rarfile.RarFile(str(path)) as rf:
        if password:
            rf.setpassword(password)
        rf.extractall(path=str(dest))


def _batch_extract_iso(path: Path, dest: Path, password: str | None) -> None:
    """ISO doesn't have extractall — extract members one by one but with a single open."""
    import pycdlib
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        members: list[_ArchiveMember] = []
        _walk_iso(iso, "/", members)
        for m in members:
            if m.is_directory:
                continue
            output = dest / m.path
            output.parent.mkdir(parents=True, exist_ok=True)
            iso_path = "/" + m.path
            try:
                iso.get_file_from_iso(str(output), joliet_path=iso_path)
            except Exception:
                try:
                    iso.get_file_from_iso(str(output), iso_path=iso_path + ";1")
                except Exception:
                    log.warning("iso_extract_member_failed", member=m.path)
    finally:
        iso.close()


def _batch_extract_cab(path: Path, dest: Path, password: str | None) -> None:
    import subprocess
    result = subprocess.run(
        ["cabextract", "-d", str(dest), str(path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cabextract batch failed: {result.stderr.strip()}")


# ── Dispatch tables ──────────────────────────────────────────────────────────

_BATCH_EXTRACT_FN: dict[str, Any] = {
    "zip": _batch_extract_zip,
    "tar": _batch_extract_tar, "tar.gz": _batch_extract_tar, "tar.bz2": _batch_extract_tar, "tar.xz": _batch_extract_tar,
    "tgz": _batch_extract_tar, "tbz2": _batch_extract_tar, "txz": _batch_extract_tar,
    "7z": _batch_extract_7z,
    "rar": _batch_extract_rar,
    "iso": _batch_extract_iso,
    "cab": _batch_extract_cab,
}

_LIST_FN: dict[str, Any] = {
    "zip": _list_zip,
    "tar": _list_tar, "tar.gz": _list_tar, "tar.bz2": _list_tar, "tar.xz": _list_tar,
    "tgz": _list_tar, "tbz2": _list_tar, "txz": _list_tar,
    "7z": _list_7z,
    "rar": _list_rar,
    "iso": _list_iso,
    "cab": _list_cab,
}

_EXTRACT_FN: dict[str, Any] = {
    "zip": _extract_zip,
    "tar": _extract_tar, "tar.gz": _extract_tar, "tar.bz2": _extract_tar, "tar.xz": _extract_tar,
    "tgz": _extract_tar, "tbz2": _extract_tar, "txz": _extract_tar,
    "7z": _extract_7z,
    "rar": _extract_rar,
    "iso": _extract_iso,
    "cab": _extract_cab,
}

_ENCRYPTED_FN: dict[str, Any] = {
    "zip": _is_zip_encrypted,
    "7z": _is_7z_encrypted,
    "rar": _is_rar_encrypted,
}


# ── Handler ──────────────────────────────────────────────────────────────────

@register_handler
class ArchiveHandler(FormatHandler):
    """Handler for compressed archive files."""

    EXTENSIONS = [
        "zip",
        "tar", "tar.gz", "tgz", "tar.bz2", "tbz2", "tar.xz", "txz",
        "7z", "rar", "cab", "iso",
    ]

    def ingest(self, file_path: Path, **kwargs) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        depth = kwargs.get("depth", 0)
        tracker: ExtractionTracker = kwargs.get("_tracker", ExtractionTracker())

        fmt = _get_archive_format(file_path)
        log.info("archive_ingest_start", filename=file_path.name, format=fmt, depth=depth)

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=fmt,
        )

        # Depth check
        depth_err = check_nesting_depth(depth)
        if depth_err:
            model.warnings.append(depth_err)
            log.warning("archive_depth_exceeded", filename=file_path.name, depth=depth)
            model.add_element(Element(
                type=ElementType.HEADING, content=f"Archive: {file_path.name}", attributes={"level": 1},
            ))
            model.add_element(Element(type=ElementType.PARAGRAPH, content=f"**Skipped:** {depth_err}"))
            return model

        # Quine check
        archive_hash = _compute_hash(file_path)
        quine_err = tracker.push_hash(archive_hash)
        if quine_err:
            model.warnings.append(quine_err)
            model.add_element(Element(
                type=ElementType.HEADING, content=f"Archive: {file_path.name}", attributes={"level": 1},
            ))
            model.add_element(Element(type=ElementType.PARAGRAPH, content=f"**Skipped:** {quine_err}"))
            return model

        # Password handling
        password = self._find_password(file_path, fmt)
        is_encrypted = password is not None and password != ""
        if password is None:
            model.warnings.append("Password-protected archive: all passwords exhausted")
            model.add_element(Element(
                type=ElementType.HEADING, content=f"Archive: {file_path.name}", attributes={"level": 1},
            ))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="**Cannot open:** archive is password-protected and no working password was found.",
            ))
            return model

        # List members
        list_fn = _LIST_FN.get(fmt)
        if not list_fn:
            model.warnings.append(f"No list function for format: {fmt}")
            return model

        try:
            members = list_fn(file_path, password)
        except Exception as exc:
            model.warnings.append(f"Failed to list archive contents: {exc}")
            log.error("archive_list_failed", filename=file_path.name, error=str(exc))
            model.add_element(Element(
                type=ElementType.HEADING, content=f"Archive: {file_path.name}", attributes={"level": 1},
            ))
            model.add_element(Element(type=ElementType.PARAGRAPH, content=f"**Error:** {exc}"))
            return model

        file_members = [m for m in members if not m.is_directory]
        total_uncompressed = sum(m.size for m in file_members)

        # Entry count check
        entry_err = check_entry_count(len(file_members))
        if entry_err:
            model.warnings.append(entry_err)

        # Total size check
        size_err = tracker.add_bytes(total_uncompressed)
        if size_err:
            model.warnings.append(size_err)
            model.add_element(Element(
                type=ElementType.HEADING, content=f"Archive: {file_path.name}", attributes={"level": 1},
            ))
            model.add_element(Element(type=ElementType.PARAGRAPH, content=f"**Skipped:** {size_err}"))
            tracker.pop_hash(archive_hash)
            return model

        # Build summary heading
        stat = file_path.stat()
        model.add_element(Element(
            type=ElementType.HEADING, content=f"Archive: {file_path.name}", attributes={"level": 1},
        ))

        # Metadata table
        meta_rows = [
            ["Format", fmt],
            ["Archive Size", _human_size(stat.st_size)],
            ["Files", str(len(file_members))],
            ["Total Uncompressed", _human_size(total_uncompressed)],
            ["SHA-256", f"`{archive_hash}`"],
        ]
        if is_encrypted:
            meta_rows.append(["Password Protected", "Yes"])
        model.add_element(Element(
            type=ElementType.TABLE,
            content=[["Property", "Value"]] + meta_rows,
        ))

        # Contents table
        contents_header = ["File", "Size", "Modified", "Type"]
        contents_rows = []
        for m in sorted(file_members, key=lambda x: x.path):
            mtime = m.modified_at.strftime("%Y-%m-%d %H:%M") if m.modified_at else "—"
            contents_rows.append([f"`{m.path}`", _human_size(m.size), mtime, m.ext or "—"])

        if contents_rows:
            model.add_element(Element(
                type=ElementType.HEADING, content="Contents", attributes={"level": 2},
            ))
            model.add_element(Element(
                type=ElementType.TABLE,
                content=[contents_header] + contents_rows,
            ))

        # ── Phase 1: Batch extraction ───────────────────────────────────
        # Extract all files at once — one archive open/parse cycle.
        # Much faster than per-member extraction over NAS or HDD.
        temp_dir = Path(tempfile.mkdtemp(prefix=f"markflow_archive_{depth}_"))
        batch_fn = _BATCH_EXTRACT_FN.get(fmt)
        extract_fn = _EXTRACT_FN.get(fmt)
        converted_count = 0
        error_count = 0

        try:
            # Try batch extraction first (single archive read)
            batch_ok = False
            if batch_fn:
                try:
                    t_extract = time.perf_counter()
                    batch_fn(file_path, temp_dir, password)
                    batch_ok = True
                    extract_ms = int((time.perf_counter() - t_extract) * 1000)
                    log.info("archive_batch_extract",
                             filename=file_path.name, members=len(file_members),
                             duration_ms=extract_ms)
                except Exception as exc:
                    log.warning("archive_batch_extract_failed",
                                filename=file_path.name, error=str(exc),
                                msg="Falling back to per-member extraction")

            # ── Phase 2: Convert inner files ─────────────────────────────
            # Separate members into archives (sequential, recursive) and
            # regular files (parallelizable).
            nested_members = []
            convertible_members = []
            for member in file_members:
                if member.is_archive and depth < MAX_NESTING_DEPTH:
                    nested_members.append(member)
                else:
                    handler = get_handler(member.ext)
                    if handler and not isinstance(handler, ArchiveHandler):
                        convertible_members.append((member, handler))

            # Choose parallel thread count based on file count
            # (CPU-bound conversion — use cores, not I/O threads)
            inner_threads = min(max(len(convertible_members), 1), os.cpu_count() or 4, 8)

            # Error rate monitor — abort if source becomes unreachable mid-extraction
            error_monitor = ErrorRateMonitor(window_size=50, min_ops=10)

            def _convert_member(member: _ArchiveMember, handler: FormatHandler) -> tuple[str, str | None, str | None]:
                """Convert a single extracted file. Returns (member_path, md_text, error)."""
                extracted = temp_dir / member.path
                if not extracted.exists():
                    # Batch failed for this file — try per-member extraction
                    if extract_fn and not batch_ok:
                        try:
                            extracted = extract_fn(file_path, member, temp_dir, password)
                        except Exception as exc:
                            error_monitor.record_error(str(exc))
                            return (member.path, None, f"extraction failed: {exc}")
                    if not extracted.exists():
                        return (member.path, None, None)  # skip silently

                try:
                    inner_model = handler.ingest(extracted)
                    md_text = _model_to_markdown(inner_model)
                    error_monitor.record_success()
                    return (member.path, md_text if md_text.strip() else None, None)
                except Exception as exc:
                    error_monitor.record_error(str(exc))
                    return (member.path, None, f"conversion failed: {exc}")

            # Parallel conversion of regular files
            results: list[tuple[str, str | None, str | None]] = []
            if convertible_members and inner_threads > 1:
                with ThreadPoolExecutor(
                    max_workers=inner_threads,
                    thread_name_prefix="archive-conv",
                ) as executor:
                    futures = {
                        executor.submit(_convert_member, m, h): m.path
                        for m, h in convertible_members
                    }
                    for future in as_completed(futures):
                        try:
                            results.append(future.result())
                        except Exception as exc:
                            results.append((futures[future], None, str(exc)))
                        # Check error rate — cancel remaining futures if source is gone
                        if error_monitor.should_abort():
                            log.error("archive_error_rate_abort",
                                      filename=file_path.name,
                                      total_errors=error_monitor.total_errors)
                            for f in futures:
                                f.cancel()
                            break
            else:
                # Single-threaded fallback (small archives or single file)
                for m, h in convertible_members:
                    results.append(_convert_member(m, h))
                    if error_monitor.should_abort():
                        log.error("archive_error_rate_abort",
                                  filename=file_path.name,
                                  total_errors=error_monitor.total_errors)
                        break

            # Sort results by original member path for deterministic output
            results.sort(key=lambda r: r[0])

            # Append converted content to model
            for member_path, md_text, error in results:
                if error:
                    error_count += 1
                    model.warnings.append(f"{member_path}: {error}")
                    log.warning("archive_member_convert_failed",
                                member=member_path, error=error)
                elif md_text:
                    model.add_element(Element(
                        type=ElementType.HEADING,
                        content=member_path,
                        attributes={"level": 2},
                    ))
                    model.add_element(Element(
                        type=ElementType.PARAGRAPH,
                        content=md_text,
                    ))
                    converted_count += 1

            # Handle nested archives sequentially (recursive, can't parallelize safely)
            if not error_monitor.aborted:
                for member in nested_members:
                    if error_monitor.should_abort():
                        log.error("archive_nested_abort",
                                  filename=file_path.name,
                                  remaining=len(nested_members))
                        break

                    extracted = temp_dir / member.path
                    if not extracted.exists() and extract_fn and not batch_ok:
                        try:
                            extracted = extract_fn(file_path, member, temp_dir, password)
                        except Exception as exc:
                            error_count += 1
                            error_monitor.record_error(str(exc))
                            model.warnings.append(f"{member.path}: extraction failed: {exc}")
                            continue

                    if not extracted.exists():
                        continue

                    nested_handler = ArchiveHandler()
                    try:
                        nested_model = nested_handler.ingest(
                            extracted, depth=depth + 1, _tracker=tracker,
                        )
                        model.add_element(Element(
                            type=ElementType.HEADING,
                            content=f"Nested: {member.path}",
                            attributes={"level": 2},
                        ))
                        for elem in nested_model.elements:
                            model.add_element(elem)
                        converted_count += 1
                        error_monitor.record_success()
                    except Exception as exc:
                        error_count += 1
                        error_monitor.record_error(str(exc))
                        model.warnings.append(f"{member.path}: nested archive failed: {exc}")
                        log.warning("archive_nested_failed",
                                    member=member.path, error=str(exc))

        finally:
            # CRITICAL: Always clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            tracker.pop_hash(archive_hash)

        # Summary line
        summary = f"Processed {len(file_members)} files: {converted_count} converted"
        if error_count:
            summary += f", {error_count} errors"
        if error_monitor.aborted:
            summary += " **[ABORTED: high error rate — source may be unreachable]**"
        extraction_mode = "batch" if batch_ok else "per-member"
        parallel_note = f" ({inner_threads} threads)" if inner_threads > 1 else ""
        summary += f" [{extraction_mode}{parallel_note}]"
        model.add_element(Element(type=ElementType.PARAGRAPH, content=f"*{summary}*"))

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("archive_ingest_complete", filename=file_path.name,
                 members=len(file_members), converted=converted_count,
                 errors=error_count, extraction_mode=extraction_mode,
                 inner_threads=inner_threads, aborted=error_monitor.aborted,
                 duration_ms=duration_ms)

        return model

    def export(self, model, output_path, sidecar=None, original_path=None):
        raise NotImplementedError("Archives cannot be exported from Markdown")

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        stat = file_path.stat()
        fmt = _get_archive_format(file_path)
        return {"document_level": {"extension": f".{fmt}", "file_size": stat.st_size}}

    def _find_password(self, path: Path, fmt: str) -> str | None:
        """Try passwords via full cascade. Returns working password, "" if not
        encrypted, None if all methods fail.

        Cascade order (matches core/password_handler.py):
          1. Empty string + archive password file + session-found passwords
          2. Dictionary attack (common.txt wordlist + mutations)
          3. Brute-force (configurable charset/length/timeout)

        On success, saves the password for session reuse and to the password file.
        Respects user preferences for dictionary/brute-force enable, charset,
        max length, and timeout.
        """
        detect_fn = _ENCRYPTED_FN.get(fmt)
        if not detect_fn:
            return ""  # Format doesn't support encryption
        if not detect_fn(path):
            return ""  # Not encrypted

        list_fn = _LIST_FN.get(fmt)
        if not list_fn:
            return None

        # Load user preferences (sync-safe — called from thread)
        settings = self._load_password_settings()
        timeout = settings["timeout"]
        deadline = time.monotonic() + timeout
        total_attempts = 0

        def _try(pw: str) -> bool:
            """Test a single password. Returns True if it works."""
            try:
                list_fn(path, pw)
                return True
            except Exception:
                return False

        # Phase 1: Direct candidates (empty, file list, session-found)
        passwords = _load_passwords()
        for i, pw in enumerate(passwords):
            if time.monotonic() > deadline:
                break
            total_attempts += 1
            if _try(pw):
                log.info("archive_password_found",
                         archive=path.name, method="known", attempt=total_attempts)
                _save_found_password(pw)
                return pw

        # Phase 2: Dictionary attack + mutations
        if settings["dictionary_enabled"] and time.monotonic() < deadline:
            dictionary = _load_dictionary()
            for pw in dictionary:
                if time.monotonic() > deadline:
                    break
                total_attempts += 1
                if _try(pw):
                    log.info("archive_password_found",
                             archive=path.name, method="dictionary", attempt=total_attempts)
                    _save_found_password(pw)
                    return pw
                # Try mutations of this dictionary word
                for mut in _mutations(pw):
                    if time.monotonic() > deadline:
                        break
                    total_attempts += 1
                    if _try(mut):
                        log.info("archive_password_found",
                                 archive=path.name, method="dictionary_mutation",
                                 attempt=total_attempts)
                        _save_found_password(mut)
                        return mut

        # Phase 3: Brute-force
        if settings["brute_force_enabled"] and time.monotonic() < deadline:
            charset = _get_charset(settings["charset"])
            max_len = settings["max_length"]
            log.info("archive_brute_force_start",
                     archive=path.name, charset=settings["charset"],
                     max_length=max_len, timeout=timeout)
            for length in range(1, max_len + 1):
                if time.monotonic() > deadline:
                    break
                for combo in itertools.product(charset, repeat=length):
                    if time.monotonic() > deadline:
                        break
                    pw = "".join(combo)
                    total_attempts += 1
                    if _try(pw):
                        log.info("archive_password_found",
                                 archive=path.name, method="brute_force",
                                 attempt=total_attempts, length=length)
                        _save_found_password(pw)
                        return pw

        log.warning("archive_password_exhausted",
                    archive=path.name, attempts=total_attempts,
                    methods_tried=["known", "dictionary", "brute_force"])
        return None

    @staticmethod
    def _load_password_settings() -> dict:
        """Load password-related preferences. Safe to call from sync context."""
        # Read preferences directly from DB (sync-safe via new connection)
        # Fall back to defaults if DB unavailable
        defaults = {
            "dictionary_enabled": True,
            "brute_force_enabled": False,
            "max_length": 6,
            "charset": "all_ascii",
            "timeout": 300,
        }
        try:
            import sqlite3
            from core.database import get_db_path
            conn = sqlite3.connect(get_db_path())
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT key, value FROM user_preferences WHERE key IN (?,?,?,?,?)",
                               ("password_dictionary_enabled",
                                "password_brute_force_enabled",
                                "password_brute_force_max_length",
                                "password_brute_force_charset",
                                "password_timeout_seconds"))
            prefs = {row["key"]: row["value"] for row in cur.fetchall()}
            conn.close()
            return {
                "dictionary_enabled": prefs.get("password_dictionary_enabled", "true") == "true",
                "brute_force_enabled": prefs.get("password_brute_force_enabled", "false") == "true",
                "max_length": int(prefs.get("password_brute_force_max_length", "6")),
                "charset": prefs.get("password_brute_force_charset", "alphanumeric"),
                "timeout": int(prefs.get("password_timeout_seconds", "300")),
            }
        except Exception:
            return defaults


# ── Markdown helper ──────────────────────────────────────────────────────────

def _model_to_markdown(model: DocumentModel) -> str:
    """Render a DocumentModel to Markdown text (simplified)."""
    lines: list[str] = []
    for elem in model.elements:
        if elem.type == ElementType.HEADING:
            level = elem.attributes.get("level", 1) if elem.attributes else 1
            lines.append(f"{'#' * level} {elem.content}")
            lines.append("")
        elif elem.type == ElementType.PARAGRAPH:
            lines.append(str(elem.content))
            lines.append("")
        elif elem.type == ElementType.TABLE and isinstance(elem.content, list):
            for i, row in enumerate(elem.content):
                lines.append("| " + " | ".join(str(c) for c in row) + " |")
                if i == 0:
                    lines.append("| " + " | ".join("---" for _ in row) + " |")
            lines.append("")
        elif elem.type == ElementType.CODE_BLOCK:
            lang = (elem.attributes or {}).get("language", "")
            lines.append(f"```{lang}")
            lines.append(str(elem.content))
            lines.append("```")
            lines.append("")
        elif elem.type == ElementType.LIST:
            if isinstance(elem.content, list):
                for item in elem.content:
                    lines.append(f"- {item}")
            lines.append("")
        else:
            if elem.content:
                lines.append(str(elem.content))
                lines.append("")
    return "\n".join(lines)
