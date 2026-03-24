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
