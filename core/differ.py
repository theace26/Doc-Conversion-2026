"""
Diff engine — computes unified diffs between two versions of a converted .md file
and produces both a unified patch and a human-readable bullet summary.
"""

import difflib
import re
from dataclasses import dataclass, field

DIFF_MAX_PATCH_BYTES = 1_048_576  # 1 MB


@dataclass
class DiffResult:
    patch: str | None = None
    patch_truncated: bool = False
    summary: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0


def compute_diff(old_text: str, new_text: str) -> DiffResult:
    """Compute unified diff between old and new text, plus bullet summary."""
    if old_text == new_text:
        return DiffResult()

    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile="previous", tofile="current",
        lineterm="",
        n=3,
    ))

    result = DiffResult()

    # Count added/removed
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            result.lines_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            result.lines_removed += 1

    # Build raw patch
    raw_patch = "\n".join(diff_lines)
    if len(raw_patch.encode("utf-8", errors="replace")) > DIFF_MAX_PATCH_BYTES:
        result.patch = None
        result.patch_truncated = True
    else:
        result.patch = raw_patch

    # Build summary
    result.summary = _build_summary(diff_lines)

    return result


def _build_summary(diff_lines: list[str]) -> list[str]:
    """Parse diff output into human-readable bullet summary."""
    bullets: list[str] = []

    # Track table row changes for aggregation
    table_adds = 0
    table_removes = 0
    in_table_run = False

    def _flush_table():
        nonlocal table_adds, table_removes, in_table_run
        if table_adds or table_removes:
            parts = []
            if table_adds:
                parts.append(f"{table_adds} rows added")
            if table_removes:
                parts.append(f"{table_removes} rows removed")
            bullets.append(f"Table updated: {', '.join(parts)}")
        table_adds = 0
        table_removes = 0
        in_table_run = False

    for line in diff_lines:
        # Skip diff headers
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue

        is_add = line.startswith("+") and not line.startswith("+++")
        is_remove = line.startswith("-") and not line.startswith("---")

        if not is_add and not is_remove:
            if in_table_run:
                _flush_table()
            continue

        content = line[1:].strip()
        if not content:
            if in_table_run:
                _flush_table()
            continue

        # Table row detection
        if content.startswith("|"):
            in_table_run = True
            if is_add:
                table_adds += 1
            else:
                table_removes += 1
            continue
        elif in_table_run:
            _flush_table()

        # Heading detection
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", content)
        if heading_match:
            heading_text = heading_match.group(2).strip()
            bullets.append(f"Section '{heading_text}' modified")
            continue

        # Regular add/remove
        truncated = content[:80] + "..." if len(content) > 80 else content
        if is_add:
            bullets.append(f"Added: {truncated}")
        else:
            bullets.append(f"Removed: {truncated}")

    # Flush any remaining table changes
    _flush_table()

    # Deduplicate consecutive identical bullets
    deduped: list[str] = []
    for b in bullets:
        if not deduped or deduped[-1] != b:
            deduped.append(b)

    # Cap at 20 items
    if len(deduped) > 20:
        remaining = len(deduped) - 19
        deduped = deduped[:19]
        deduped.append(f"... and {remaining} more changes")

    return deduped
