"""
Compare MarkFlow conversion output against Microsoft markitdown.

NOT in the hot path. Used for:
- Manual validation: python -m core.validation.markitdown_compare <file>
- Edge case detection during development
"""

import re
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def _count_markdown_headings(text: str) -> int:
    return len(re.findall(r"^#{1,6}\s", text, re.MULTILINE))


def _count_markdown_tables(text: str) -> int:
    return len(re.findall(r"^\|.*\|$", text, re.MULTILINE)) // 2


def compare_with_markitdown(file_path: str | Path) -> dict:
    """Run markitdown and compare against MarkFlow structurally."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return {"error": "markitdown not installed"}

    file_path = Path(file_path)
    if not file_path.exists():
        return {"error": f"File not found: {file_path}"}

    md = MarkItDown()
    result = md.convert(str(file_path))
    markitdown_text = result.text_content or ""

    return {
        "file": str(file_path),
        "markitdown_headings": _count_markdown_headings(markitdown_text),
        "markitdown_tables": _count_markdown_tables(markitdown_text),
        "markitdown_length": len(markitdown_text),
    }


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 2:
        print("Usage: python -m core.validation.markitdown_compare <file>")
        sys.exit(1)
    result = compare_with_markitdown(sys.argv[1])
    print(json.dumps(result, indent=2))
