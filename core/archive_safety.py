"""
Zip-bomb and archive safety checks.

Validates archives before extraction to prevent resource exhaustion:
  - Compression ratio check (per-entry)
  - Total uncompressed size cap
  - Entry count cap
  - Nesting depth limit
  - Quine detection (same hash in the recursion chain)

Environment variables:
  - ARCHIVE_MAX_DEPTH (default: 20)
  - ARCHIVE_MAX_SIZE_GB (default: 50)
  - ARCHIVE_MAX_ENTRIES (default: 100000)
  - ARCHIVE_MAX_RATIO (default: 200)
"""

import os

import structlog

log = structlog.get_logger(__name__)

MAX_NESTING_DEPTH = int(os.environ.get("ARCHIVE_MAX_DEPTH", "20"))
MAX_DECOMPRESSED_BYTES = int(os.environ.get("ARCHIVE_MAX_SIZE_GB", "50")) * 1024 * 1024 * 1024
MAX_ENTRIES = int(os.environ.get("ARCHIVE_MAX_ENTRIES", "100000"))
MAX_RATIO = int(os.environ.get("ARCHIVE_MAX_RATIO", "200"))

# All file extensions considered archive formats
ARCHIVE_EXTENSIONS = frozenset({
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
    ".tar.xz", ".txz", ".7z", ".rar", ".cab", ".iso",
})


def check_nesting_depth(current_depth: int) -> str | None:
    """Returns error string if depth exceeds limit, None if OK."""
    if current_depth > MAX_NESTING_DEPTH:
        return f"Max nesting depth ({MAX_NESTING_DEPTH}) exceeded at depth {current_depth}"
    return None


def check_entry_count(count: int) -> str | None:
    """Returns error string if entry count exceeds limit, None if OK."""
    if count > MAX_ENTRIES:
        return f"Archive has {count:,} entries — exceeds limit of {MAX_ENTRIES:,}"
    return None


def check_total_size(total_uncompressed_bytes: int) -> str | None:
    """Returns error string if total uncompressed size exceeds limit, None if OK."""
    if total_uncompressed_bytes > MAX_DECOMPRESSED_BYTES:
        gb = total_uncompressed_bytes / (1024 * 1024 * 1024)
        limit_gb = MAX_DECOMPRESSED_BYTES / (1024 * 1024 * 1024)
        return f"Total uncompressed size {gb:.1f} GB exceeds limit of {limit_gb:.0f} GB"
    return None


def check_compression_ratio(compressed_size: int, uncompressed_size: int) -> str | None:
    """Returns error string if ratio is suspicious, None if OK."""
    if compressed_size <= 0:
        return None
    ratio = uncompressed_size / compressed_size
    if ratio > MAX_RATIO:
        return f"Compression ratio {ratio:.0f}:1 exceeds limit of {MAX_RATIO}:1 — possible zip bomb"
    return None


def check_quine(archive_hash: str, ancestor_hashes: set[str]) -> str | None:
    """Returns error string if this archive hash appeared in the recursion chain."""
    if archive_hash in ancestor_hashes:
        return f"Quine detected: archive hash {archive_hash[:16]}... already seen in recursion chain"
    return None


class ExtractionTracker:
    """Tracks cumulative extracted bytes across a recursion chain for zip-bomb protection."""

    def __init__(self):
        self.total_bytes: int = 0
        self.ancestor_hashes: set[str] = set()

    def add_bytes(self, byte_count: int) -> str | None:
        """Track bytes and return error if limit exceeded, None if OK."""
        self.total_bytes += byte_count
        return check_total_size(self.total_bytes)

    def push_hash(self, archive_hash: str) -> str | None:
        """Add a hash to the chain. Returns error if quine detected."""
        error = check_quine(archive_hash, self.ancestor_hashes)
        if error:
            return error
        self.ancestor_hashes.add(archive_hash)
        return None

    def pop_hash(self, archive_hash: str) -> None:
        """Remove a hash from the chain (when leaving a recursion level)."""
        self.ancestor_hashes.discard(archive_hash)
