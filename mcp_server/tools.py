"""
MarkFlow MCP tool implementations.

Each function is a standalone async tool that accesses MarkFlow internals
directly (shared codebase, not HTTP). Returns markdown strings for Claude.
"""

import os
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))


async def search_documents(
    query: str,
    format: str | None = None,
    path_prefix: str | None = None,
    max_results: int = 10,
) -> str:
    """Search the MarkFlow document index."""
    try:
        from core.search_client import MeilisearchClient

        client = MeilisearchClient()
        if not await client.health_check():
            return "Search is unavailable — Meilisearch is not running."

        filters = []
        if format:
            filters.append(f"source_format = '{format}'")

        result = await client.search(
            index="documents",
            query=query,
            limit=min(max_results, 20),
            filter=" AND ".join(filters) if filters else None,
        )

        hits = result.get("hits", [])
        if not hits:
            return f'No results found for "{query}".'

        lines = [f'Found {len(hits)} results for "{query}":\n']
        for i, hit in enumerate(hits, 1):
            title = hit.get("title", hit.get("source_filename", "Untitled"))
            fmt = hit.get("source_format", "")
            path = hit.get("output_path", "")
            # Build preview from content or snippet
            content = hit.get("content", "")
            preview = content[:200].replace("\n", " ") + "..." if len(content) > 200 else content.replace("\n", " ")

            if path_prefix and path and not path.startswith(path_prefix):
                continue

            lines.append(f"{i}. **{title}** ({fmt})")
            if path:
                lines.append(f"   Path: {path}")
            if preview:
                lines.append(f"   Preview: {preview}")
            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        log.warning("mcp_search_error", error=str(exc))
        return f"Search error: {exc}"


async def read_document(path: str, max_tokens: int = 8000) -> str:
    """Read the full content of a converted document."""
    try:
        # Try as-is first, then relative to output dir
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = OUTPUT_DIR / path

        if not file_path.exists():
            return f"File not found: {path}"

        if not file_path.suffix.lower() == ".md":
            return f"Expected a .md file, got: {file_path.suffix}"

        content = file_path.read_text(encoding="utf-8", errors="replace")

        # Truncate if too long (rough char-to-token ratio of ~4)
        max_chars = max_tokens * 4
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — showing first {max_chars} characters of {len(content)} total]"

        return content
    except Exception as exc:
        return f"Error reading document: {exc}"


async def list_directory(path: str = "", show_stats: bool = False) -> str:
    """List documents and folders in the MarkFlow repository."""
    try:
        base = OUTPUT_DIR / path if path else OUTPUT_DIR
        if not base.exists():
            return f"Directory not found: {path or 'output root'}"

        entries = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = [f"Contents of {path or '/'}:\n"]

        dirs = [e for e in entries if e.is_dir() and not e.name.startswith("_")]
        files = [e for e in entries if e.is_file() and e.suffix.lower() == ".md"]

        for d in dirs[:50]:
            if show_stats:
                file_count = sum(1 for f in d.rglob("*.md"))
                lines.append(f"  [{d.name}/] ({file_count} files)")
            else:
                lines.append(f"  [{d.name}/]")

        for f in files[:50]:
            size = f.stat().st_size
            size_str = f"{size / 1024:.0f}KB" if size > 1024 else f"{size}B"
            lines.append(f"  {f.name} ({size_str})")

        if len(dirs) + len(files) > 100:
            lines.append(f"\n  ... and more ({len(dirs)} dirs, {len(files)} files total)")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing directory: {exc}"


async def get_conversion_status(batch_id: str | None = None) -> str:
    """Get conversion status."""
    try:
        from core.database import get_batch_state, db_fetch_all

        if batch_id:
            state = await get_batch_state(batch_id)
            if not state:
                return f"Batch '{batch_id}' not found."
            return (
                f"Batch {batch_id}:\n"
                f"  Status: {state['status']}\n"
                f"  Files: {state['completed_files']}/{state['total_files']} completed\n"
                f"  Failed: {state['failed_files']}\n"
                f"  OCR flags pending: {state.get('ocr_flags_pending', 0)}"
            )

        # Overall recent status
        recent = await db_fetch_all(
            "SELECT * FROM conversion_history ORDER BY created_at DESC LIMIT 10"
        )
        if not recent:
            return "No recent conversions."

        lines = ["Recent conversions:\n"]
        for r in recent:
            status = r["status"]
            icon = "+" if status == "success" else "x"
            lines.append(
                f"  [{icon}] {r['source_filename']} ({r['source_format']}) — "
                f"{status} — {r['created_at']}"
            )

        # Active bulk jobs
        from core.database import list_bulk_jobs
        jobs = await list_bulk_jobs(limit=3)
        active = [j for j in jobs if j["status"] in ("running", "scanning")]
        if active:
            lines.append("\nActive bulk jobs:")
            for j in active:
                lines.append(
                    f"  {j['id'][:8]}... — {j['status']} — "
                    f"{j['converted']}/{j['total_files']} converted"
                )

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting status: {exc}"


async def convert_document(
    source_path: str,
    fidelity_tier: int = 2,
    ocr_mode: str = "auto",
) -> str:
    """Convert a single document to Markdown."""
    try:
        from core.converter import ConversionOrchestrator, new_batch_id

        path = Path(source_path)
        if not path.exists():
            return f"File not found: {source_path}"

        batch_id = new_batch_id()
        orch = ConversionOrchestrator()
        results = await orch.convert_batch(
            [path], "to_md", batch_id,
            options={"fidelity_tier": fidelity_tier, "ocr_mode": ocr_mode},
        )

        if not results:
            return "Conversion produced no results."

        r = results[0]
        if r.status == "success":
            return (
                f"Converted successfully!\n"
                f"  Output: {r.output_filename}\n"
                f"  Batch: {r.batch_id}\n"
                f"  Tier: {r.fidelity_tier}\n"
                f"  Duration: {r.duration_ms}ms\n"
                f"  OCR applied: {r.ocr_applied}"
            )
        else:
            return f"Conversion failed: {r.error_message}"
    except Exception as exc:
        return f"Conversion error: {exc}"


async def search_adobe_files(
    query: str,
    file_type: str | None = None,
    max_results: int = 10,
) -> str:
    """Search the Adobe creative file index."""
    try:
        from core.search_client import MeilisearchClient

        client = MeilisearchClient()
        if not await client.health_check():
            return "Search is unavailable — Meilisearch is not running."

        filters = []
        if file_type:
            filters.append(f"file_ext = '.{file_type}'")

        result = await client.search(
            index="adobe-files",
            query=query,
            limit=min(max_results, 20),
            filter=" AND ".join(filters) if filters else None,
        )

        hits = result.get("hits", [])
        if not hits:
            return f'No Adobe files found for "{query}".'

        lines = [f'Found {len(hits)} Adobe files for "{query}":\n']
        for i, hit in enumerate(hits, 1):
            path = hit.get("source_path", "")
            ext = hit.get("file_ext", "")
            text = hit.get("text_content", "")
            preview = text[:150].replace("\n", " ") + "..." if len(text) > 150 else text.replace("\n", " ")

            lines.append(f"{i}. **{Path(path).name}** ({ext})")
            lines.append(f"   Path: {path}")
            if preview:
                lines.append(f"   Content: {preview}")
            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        return f"Adobe search error: {exc}"


async def get_document_summary(path: str) -> str:
    """Get summary and metadata for a document."""
    try:
        import yaml

        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = OUTPUT_DIR / path

        if not file_path.exists():
            return f"File not found: {path}"

        content = file_path.read_text(encoding="utf-8", errors="replace")

        # Extract frontmatter
        summary = None
        title = file_path.stem
        metadata = {}

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    metadata = yaml.safe_load(parts[1]) or {}
                    title = metadata.get("title", title)
                    summary = metadata.get("summary")
                except Exception:
                    pass

        # Get history record
        from core.database import db_fetch_one
        history = await db_fetch_one(
            "SELECT * FROM conversion_history WHERE output_path LIKE ? LIMIT 1",
            (f"%{file_path.name}",),
        )

        lines = [f"**{title}**\n"]

        if summary:
            lines.append(f"Summary: {summary}\n")

        lines.append("Metadata:")
        lines.append(f"  Format: {metadata.get('source_format', 'unknown')}")
        lines.append(f"  Source: {metadata.get('source_file', 'unknown')}")

        if history:
            lines.append(f"  Converted: {history['created_at']}")
            lines.append(f"  Status: {history['status']}")
            if history.get("ocr_confidence_mean"):
                lines.append(f"  OCR confidence: {history['ocr_confidence_mean']}%")

        content_length = len(content)
        lines.append(f"  Content length: {content_length} chars")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting summary: {exc}"


async def list_unrecognized(
    category: str | None = None,
    job_id: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> str:
    """List files found during bulk scans that MarkFlow could not convert."""
    try:
        from core.database import get_unrecognized_files, get_unrecognized_stats

        if page == 1 and not category and not job_id:
            stats = await get_unrecognized_stats()
            if stats["total"] == 0:
                return "No unrecognized files found. All files in the repository have handlers."
            lines = [f"**Unrecognized Files Summary** ({stats['total']} files, {_fmt_bytes(stats['total_bytes'])})\n"]
            for cat, count in stats["by_category"].items():
                lines.append(f"  {cat}: {count}")
            lines.append(f"\nTop formats: {', '.join(f'{k} ({v})' for k, v in list(stats['by_format'].items())[:10])}")
            lines.append(f"\nUse category filter to drill down. Valid categories: "
                         "disk_image, raster_image, vector_image, video, audio, "
                         "archive, executable, database, font, code, unknown")
            return "\n".join(lines)

        data = await get_unrecognized_files(
            job_id=job_id, category=category, page=page, per_page=per_page
        )
        if not data["files"]:
            return f"No unrecognized files match filters (category={category}, job_id={job_id})."

        lines = [f"**Unrecognized Files** (page {data['page']}/{data['pages']}, {data['total']} total)\n"]
        for f in data["files"]:
            size = _fmt_bytes(f.get("file_size_bytes", 0))
            cat = f.get("file_category", "unknown")
            lines.append(f"  {f['source_path']}  [{f.get('file_ext', '')}]  {cat}  {size}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing unrecognized files: {exc}"


def _fmt_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.1f} GB"


async def list_deleted_files(
    status: str = "marked_for_deletion",
    limit: int = 20,
) -> str:
    """List files in a given lifecycle state (marked_for_deletion, in_trash, or purged).

    - marked_for_deletion: files no longer found in the source share, waiting for
      the grace period to expire before moving to trash (default 36 hours)
    - in_trash: files moved to the .trash/ directory, awaiting permanent deletion
      after the retention period (default 60 days)
    - purged: permanently deleted files (DB record retained for audit)

    Use this to check what files are scheduled for deletion, what's in the trash,
    or to review the purge history before it's too late to restore.
    """
    try:
        from core.database import get_bulk_files_by_lifecycle_status

        if status not in ("marked_for_deletion", "in_trash", "purged"):
            return f"Invalid status '{status}'. Use: marked_for_deletion, in_trash, or purged."

        files = await get_bulk_files_by_lifecycle_status(status)
        if not files:
            status_labels = {
                "marked_for_deletion": "marked for deletion",
                "in_trash": "in trash",
                "purged": "purged",
            }
            return f"No files are currently {status_labels.get(status, status)}."

        files = files[:limit]
        lines = [f"**{len(files)} files with status '{status}':**\n"]

        for f in files:
            path = f.get("source_path", "unknown")
            name = Path(path).name
            size = _fmt_bytes(f.get("file_size_bytes", 0))

            timestamps = []
            if status == "marked_for_deletion" and f.get("marked_for_deletion_at"):
                timestamps.append(f"marked: {f['marked_for_deletion_at']}")
            elif status == "in_trash" and f.get("moved_to_trash_at"):
                timestamps.append(f"trashed: {f['moved_to_trash_at']}")
            elif status == "purged" and f.get("purged_at"):
                timestamps.append(f"purged: {f['purged_at']}")

            ts_str = f" ({', '.join(timestamps)})" if timestamps else ""
            lines.append(f"  {name} — {size}{ts_str}")
            lines.append(f"    Path: {path}")
            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        log.warning("mcp_list_deleted_error", error=str(exc))
        return f"Error listing deleted files: {exc}"


async def get_file_history(source_path: str) -> str:
    """Get the complete version history for a file identified by its source path.

    Returns all recorded changes including: initial indexing, content modifications
    (with diff summaries), file moves, deletion marks, trash/purge events, and
    restorations. Each version includes a timestamp, change type, and human-readable
    summary bullets where available.

    Use this when you need to understand what happened to a specific file over time,
    when it was last modified, or why it might have been deleted.
    """
    try:
        from core.database import get_bulk_file_by_path, get_version_history
        import json

        file_rec = await get_bulk_file_by_path(source_path)
        if not file_rec:
            return f"File not found: {source_path}"

        file_id = file_rec["id"]
        versions = await get_version_history(file_id)

        if not versions:
            return (
                f"**{Path(source_path).name}**\n"
                f"Status: {file_rec.get('lifecycle_status', 'active')}\n"
                f"No version history recorded yet (newly indexed)."
            )

        lines = [
            f"**{Path(source_path).name}** — {len(versions)} version(s)\n"
            f"Current status: {file_rec.get('lifecycle_status', 'active')}\n"
        ]

        for v in versions:
            date = v.get("recorded_at", "")
            change_type = v.get("change_type", "unknown")
            vnum = v.get("version_number", "?")

            lines.append(f"**v{vnum}** — {change_type} — {date}")

            # Summary bullets
            summary = v.get("diff_summary")
            if summary:
                try:
                    bullets = json.loads(summary) if isinstance(summary, str) else summary
                    for bullet in bullets[:10]:
                        lines.append(f"  - {bullet}")
                except (json.JSONDecodeError, TypeError):
                    pass

            notes = v.get("notes")
            if notes:
                lines.append(f"  Note: {notes}")

            lines.append("")

        return "\n".join(lines)
    except Exception as exc:
        log.warning("mcp_file_history_error", error=str(exc))
        return f"Error getting file history: {exc}"
