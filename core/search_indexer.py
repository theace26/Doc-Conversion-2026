"""
Meilisearch index management — creates indexes, indexes documents/Adobe files,
and provides rebuild functionality.

Two indexes:
  - 'documents': converted Markdown files
  - 'adobe-files': Adobe creative file index entries
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from core.search_client import MeilisearchClient, get_meili_client

log = structlog.get_logger(__name__)

# ── Index settings ───────────────────────────────────────────────────────────

DOCUMENTS_INDEX_SETTINGS = {
    "searchableAttributes": [
        "title",
        "content",
        "headings",
        "source_filename",
    ],
    "filterableAttributes": [
        "source_format",
        "fidelity_tier",
        "has_ocr",
        "job_id",
        "relative_path_prefix",
    ],
    "sortableAttributes": [
        "converted_at",
        "file_size_bytes",
    ],
    "displayedAttributes": [
        "id", "title", "source_filename", "source_format", "relative_path",
        "output_path", "source_path", "content_preview", "headings",
        "fidelity_tier", "has_ocr", "converted_at", "file_size_bytes", "job_id",
    ],
    "rankingRules": [
        "words", "typo", "proximity", "attribute", "sort", "exactness",
    ],
}

ADOBE_INDEX_SETTINGS = {
    "searchableAttributes": ["title", "text_content", "source_filename", "keywords"],
    "filterableAttributes": ["file_ext", "creator", "job_id"],
    "sortableAttributes": ["indexed_at"],
    "displayedAttributes": [
        "id", "source_filename", "file_ext", "source_path", "title",
        "creator", "keywords", "text_preview", "indexed_at", "job_id",
    ],
}


@dataclass
class RebuildStatus:
    documents_indexed: int = 0
    adobe_indexed: int = 0
    errors: int = 0


def _doc_id(source_path: str) -> str:
    """Generate a Meilisearch-safe document ID from source path."""
    return hashlib.sha256(source_path.encode()).hexdigest()[:16]


def _extract_headings(content: str) -> list[str]:
    """Extract H1-H3 text from markdown content."""
    headings = []
    for line in content.split("\n"):
        m = re.match(r"^(#{1,3})\s+(.+)$", line)
        if m:
            headings.append(m.group(2).strip())
    return headings


def _strip_for_indexing(content: str) -> str:
    """Strip frontmatter, image refs, and code fences for indexing."""
    # Strip YAML frontmatter
    content = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
    # Strip image references
    content = re.sub(r"!\[.*?\]\(.*?\)", "", content)
    # Strip inline code
    content = re.sub(r"`[^`]+`", "", content)
    return content.strip()


class SearchIndexer:
    def __init__(self, client: MeilisearchClient | None = None):
        self.client = client or get_meili_client()

    async def ensure_indexes(self) -> None:
        """Create both indexes with correct settings if they don't exist."""
        if not await self.client.health_check():
            log.warning("meilisearch_not_available_for_index_setup")
            return

        await self.client.create_index("documents", "id")
        await self.client.update_index_settings("documents", DOCUMENTS_INDEX_SETTINGS)

        await self.client.create_index("adobe-files", "id")
        await self.client.update_index_settings("adobe-files", ADOBE_INDEX_SETTINGS)

        log.info("meilisearch_indexes_ready")

    async def index_document(self, md_path: Path, job_id: str = "") -> bool:
        """
        Read md_path, extract content, build document dict, add to 'documents' index.
        Returns True if indexed, False if unavailable.
        """
        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("search_index_read_fail", path=str(md_path), error=str(exc))
            return False

        # Parse frontmatter
        from core.metadata import parse_frontmatter
        metadata, body = parse_frontmatter(content)
        markflow_meta = metadata.get("markflow", {})

        source_filename = markflow_meta.get("source_file", md_path.stem)
        source_format = markflow_meta.get("source_format", "")
        source_path = markflow_meta.get("source_path", "")

        # Strip for indexing
        indexable_content = _strip_for_indexing(body)
        headings = _extract_headings(body)

        title = metadata.get("title", "") or (headings[0] if headings else md_path.stem)

        doc = {
            "id": _doc_id(str(md_path)),
            "title": title,
            "source_filename": source_filename,
            "source_format": source_format,
            "source_path": source_path,
            "output_path": str(md_path),
            "relative_path": str(md_path.name),
            "relative_path_prefix": "",
            "content": indexable_content,
            "content_preview": indexable_content[:500],
            "headings": headings,
            "fidelity_tier": markflow_meta.get("fidelity_tier", 1),
            "has_ocr": markflow_meta.get("ocr_applied", False),
            "converted_at": markflow_meta.get("converted_at", ""),
            "file_size_bytes": md_path.stat().st_size,
            "job_id": job_id,
        }

        task_uid = await self.client.add_documents("documents", [doc])
        return task_uid is not None

    async def index_adobe_file(self, adobe_result, job_id: str = "") -> bool:
        """Build adobe document dict from AdobeIndexResult, add to 'adobe-files' index."""
        metadata = adobe_result.metadata or {}
        text_layers = adobe_result.text_layers or []
        text_content = "\n".join(text_layers)

        doc = {
            "id": _doc_id(str(adobe_result.source_path)),
            "source_filename": adobe_result.source_path.name,
            "file_ext": adobe_result.file_ext,
            "source_path": str(adobe_result.source_path),
            "title": metadata.get("Title", "") or adobe_result.source_path.stem,
            "creator": metadata.get("Creator", "") or metadata.get("Author", ""),
            "keywords": str(metadata.get("Keywords", "")),
            "text_content": text_content,
            "text_preview": text_content[:300],
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "job_id": job_id,
        }

        task_uid = await self.client.add_documents("adobe-files", [doc])
        if task_uid is not None:
            # Mark as indexed in DB
            from core.database import get_adobe_index_entry, mark_adobe_meili_indexed
            entry = await get_adobe_index_entry(str(adobe_result.source_path))
            if entry:
                await mark_adobe_meili_indexed(entry["id"])
        return task_uid is not None

    async def remove_document(self, source_path: str) -> None:
        """Remove document from 'documents' index."""
        await self.client.delete_document("documents", _doc_id(source_path))

    async def rebuild_index(self, job_id: str | None = None) -> RebuildStatus:
        """Walk all converted files in bulk_files and re-index."""
        from core.database import get_bulk_files, get_unindexed_adobe_entries

        status = RebuildStatus()

        # Re-index documents
        if job_id:
            files = await get_bulk_files(job_id, status="converted")
        else:
            from core.database import db_fetch_all
            files = await db_fetch_all(
                "SELECT * FROM bulk_files WHERE status='converted'"
            )

        for f in files:
            output_path = f.get("output_path")
            if not output_path:
                continue
            md_path = Path(output_path)
            if md_path.exists():
                ok = await self.index_document(md_path, f.get("job_id", ""))
                if ok:
                    status.documents_indexed += 1
                else:
                    status.errors += 1
            else:
                status.errors += 1

        # Re-index Adobe entries
        adobe_entries = await get_unindexed_adobe_entries(limit=10000)
        for entry in adobe_entries:
            from core.adobe_indexer import AdobeIndexResult
            result = AdobeIndexResult(
                source_path=Path(entry["source_path"]),
                file_ext=entry["file_ext"],
                file_size_bytes=entry.get("file_size_bytes", 0),
                metadata=entry.get("metadata") or {},
                text_layers=entry.get("text_layers") or [],
            )
            ok = await self.index_adobe_file(result, "")
            if ok:
                status.adobe_indexed += 1
            else:
                status.errors += 1

        return status


# ── Module-level singleton ───────────────────────────────────────────────────

_indexer: SearchIndexer | None = None


def get_search_indexer() -> SearchIndexer | None:
    global _indexer
    if _indexer is None:
        _indexer = SearchIndexer()
    return _indexer
