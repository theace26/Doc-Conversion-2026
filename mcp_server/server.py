"""
MarkFlow MCP Server — exposes MarkFlow tools to Claude.ai and other MCP clients.

Run with: python -m mcp_server.server
Port: MCP_PORT env var (default 8001)
"""

import os
import sys

# Add project root to path so we can import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

# Initialize logging
from core.logging_config import configure_logging
configure_logging()

import structlog
log = structlog.get_logger(__name__)

# Create MCP server
mcp = FastMCP(
    "MarkFlow",
    description="Search, read, and convert documents in the MarkFlow repository.",
)

# MCP auth token (optional)
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")


@mcp.tool()
async def search_documents(
    query: str,
    format: str | None = None,
    path_prefix: str | None = None,
    max_results: int = 10,
) -> str:
    """
    Search the MarkFlow document index for files matching the query.
    Returns ranked results with document titles, paths, and content previews.

    Use this when the user asks to find documents, search for information
    across their file repository, or look up a specific topic.

    Args:
        query: Natural language search query
        format: Optional filter - 'docx', 'pdf', 'pptx', 'xlsx', or 'csv'
        path_prefix: Optional folder path prefix to restrict search scope
        max_results: Number of results to return (1-20, default 10)
    """
    from mcp_server.tools import search_documents as _search
    return await _search(query, format, path_prefix, max_results)


@mcp.tool()
async def read_document(
    path: str,
    max_tokens: int = 8000,
) -> str:
    """
    Read the full content of a converted document from the repository.
    Returns the Markdown content of the document.

    Use this when the user asks to read, summarize, or analyze a specific
    document. The path should come from search_documents results.

    Args:
        path: Relative path to the .md file (e.g. 'dept/finance/Q4_Report.md')
        max_tokens: Maximum content length to return (default 8000)
    """
    from mcp_server.tools import read_document as _read
    return await _read(path, max_tokens)


@mcp.tool()
async def list_directory(
    path: str = "",
    show_stats: bool = False,
) -> str:
    """
    List documents and folders in the MarkFlow repository.
    Returns a directory tree of converted files.

    Use this when the user wants to browse what's in the repository,
    see what folders exist, or understand the structure.

    Args:
        path: Relative path within the repository (empty = root)
        show_stats: Include file count and last-modified date per folder
    """
    from mcp_server.tools import list_directory as _list
    return await _list(path, show_stats)


@mcp.tool()
async def get_conversion_status(
    batch_id: str | None = None,
) -> str:
    """
    Get the status of document conversions.
    If batch_id provided: status of that specific batch.
    Otherwise: overall system status (recent conversions, active jobs).

    Use this when the user asks about conversion progress, recent activity,
    or whether a specific file has been converted.

    Args:
        batch_id: Optional batch ID to check specific conversion status
    """
    from mcp_server.tools import get_conversion_status as _status
    return await _status(batch_id)


@mcp.tool()
async def convert_document(
    source_path: str,
    fidelity_tier: int = 2,
    ocr_mode: str = "auto",
) -> str:
    """
    Convert a single document to Markdown.
    The source_path must be accessible from within the MarkFlow container.

    Use this when the user asks to convert a specific file, or when
    read_document returns a 'not found' error for a file that exists
    on the source drive.

    Args:
        source_path: Container path to the source file (e.g. '/host/c/Users/.../file.docx')
        fidelity_tier: 1 (structure), 2 (styles), or 3 (patch original)
        ocr_mode: 'auto', 'force', or 'skip'
    """
    from mcp_server.tools import convert_document as _convert
    return await _convert(source_path, fidelity_tier, ocr_mode)


@mcp.tool()
async def search_adobe_files(
    query: str,
    file_type: str | None = None,
    max_results: int = 10,
) -> str:
    """
    Search the Adobe creative file index for .ai, .psd, .indd, .aep,
    .prproj, and .xd files.

    Use this when the user asks about design files, creative assets,
    Photoshop files, Illustrator files, or InDesign documents.

    Args:
        query: Natural language search query
        file_type: Optional filter - 'ai', 'psd', 'indd', 'aep', 'prproj', 'xd'
        max_results: Number of results (1-20, default 10)
    """
    from mcp_server.tools import search_adobe_files as _search
    return await _search(query, file_type, max_results)


@mcp.tool()
async def get_document_summary(
    path: str,
) -> str:
    """
    Get the AI-generated summary for a document (if available) plus
    key metadata: title, format, conversion date, OCR confidence.

    Use this for a quick overview of a document without reading its
    full content. Faster than read_document for answering 'what is this
    file about?' questions.

    Args:
        path: Relative path to the .md file
    """
    from mcp_server.tools import get_document_summary as _summary
    return await _summary(path)


def main():
    """Run the MCP server."""
    port = int(os.getenv("MCP_PORT", "8001"))

    # Initialize database before starting server
    import asyncio
    from core.database import init_db
    asyncio.run(init_db())

    log.info("mcp_server_start", port=port, tools=7)
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
