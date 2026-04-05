"""
Markdown chunker for MarkFlow vector search.

Splits a markdown document into embeddable Chunk objects, each prepended with a
contextual header so embeddings carry document and section identity.

Algorithm
---------
1. Strip YAML frontmatter (``---`` fences at the top of the file).
2. Split the remaining text on H1/H2/H3 headings into sections.
3. Large sections (>1600 chars) are subdivided with ~200-char overlap so no
   single chunk overflows a typical embedding window (~400 tokens).
4. Adjacent tiny sections (<200 chars) are merged together to avoid producing
   near-empty vectors.
5. Every chunk is prefixed with:
       [Document: {title}]
       [Section: {heading_path}]

       {content}

Public API
----------
``chunk_markdown(markdown, doc_title, doc_id, source_path) -> list[Chunk]``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LARGE_SECTION_CHARS = 1600   # ~400 tokens — subdivide above this
SMALL_SECTION_CHARS = 200    # ~50 tokens  — merge below this
OVERLAP_CHARS = 200          # overlap when splitting large sections
CHUNK_TARGET_CHARS = 1600    # target size for sub-chunks of large sections

# Heading levels we split on (H1 / H2 / H3).
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# YAML frontmatter: optional opening ``---``, content, closing ``---`` or ``...``
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n(?:---|\.\.\.)[ \t]*\n?", re.DOTALL)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A single embeddable unit of a markdown document."""

    text: str               # contextual header + chunk content
    doc_id: str = ""
    doc_title: str = ""
    heading_path: str = ""  # e.g. "Section A > Subsection B.1"
    chunk_index: int = 0
    source_path: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_frontmatter(markdown: str) -> str:
    """Remove YAML frontmatter if present."""
    return _FRONTMATTER_RE.sub("", markdown)


def _build_heading_path(stack: list[tuple[int, str]]) -> str:
    """Return a human-readable path from the active heading stack."""
    return " > ".join(title for _, title in stack) if stack else ""


def _split_into_sections(body: str) -> list[tuple[str, str]]:
    """
    Split *body* on H1/H2/H3 headings.

    Returns a list of ``(heading_path, text)`` pairs.  Text that precedes the
    first heading is emitted under an empty heading path.
    """
    sections: list[tuple[str, str]] = []
    # heading_stack holds (level, title) pairs — we maintain the hierarchy so
    # that an H3 carries its parent H2 and H1 in the path.
    heading_stack: list[tuple[int, str]] = []

    # Split the body at every H1-H3 heading, keeping the delimiters.
    parts = _HEADING_RE.split(body)
    # _HEADING_RE has 2 capture groups so split yields:
    #   [pre_text, hashes, title, text, hashes, title, text, ...]
    # i.e. groups of 3 after the first element.

    # First element is text before any heading (may be empty)
    pre_text = parts[0].strip()
    if pre_text:
        sections.append(("", pre_text))

    i = 1
    while i + 2 <= len(parts):
        hashes = parts[i]
        title = parts[i + 1].strip()
        text = parts[i + 2].strip()
        level = len(hashes)

        # Trim the stack to the current heading level
        heading_stack = [(lvl, ttl) for lvl, ttl in heading_stack if lvl < level]
        heading_stack.append((level, title))

        heading_path = _build_heading_path(heading_stack)
        sections.append((heading_path, text))
        i += 3

    return sections


def _subdivide(text: str, overlap: int = OVERLAP_CHARS,
               target: int = CHUNK_TARGET_CHARS) -> list[str]:
    """
    Split *text* into sub-chunks of up to *target* chars with *overlap*.

    Splitting prefers sentence or paragraph boundaries when possible.
    """
    if len(text) <= target:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + target, length)

        if end < length:
            # Try to break at a paragraph boundary first, then sentence.
            break_at = -1
            for sep in ("\n\n", "\n", ". ", "! ", "? ", " "):
                idx = text.rfind(sep, start + overlap, end)
                if idx != -1:
                    break_at = idx + len(sep)
                    break
            if break_at == -1:
                break_at = end

            chunks.append(text[start:break_at].strip())
            # Back up by overlap from the break point
            start = max(start + 1, break_at - overlap)
        else:
            tail = text[start:end].strip()
            if tail:
                chunks.append(tail)
            break

    return [c for c in chunks if c]


def _merge_small_sections(
    sections: list[tuple[str, str]],
    threshold: int = SMALL_SECTION_CHARS,
) -> list[tuple[str, str]]:
    """
    Merge adjacent sections that are both below *threshold* characters.

    When two consecutive sections are both tiny, the second one is appended to
    the first (keeping the first section's heading_path).  The process repeats
    until no two adjacent sections are both small.
    """
    merged = list(sections)
    changed = True
    while changed:
        changed = False
        result: list[tuple[str, str]] = []
        i = 0
        while i < len(merged):
            if (
                i + 1 < len(merged)
                and len(merged[i][1]) < threshold
                and len(merged[i + 1][1]) < threshold
            ):
                combined_text = merged[i][1] + "\n\n" + merged[i + 1][1]
                result.append((merged[i][0], combined_text.strip()))
                i += 2
                changed = True
            else:
                result.append(merged[i])
                i += 1
        merged = result
    return merged


def _make_header(doc_title: str, heading_path: str) -> str:
    """Return the contextual header string for a chunk."""
    lines = [f"[Document: {doc_title}]"]
    if heading_path:
        lines.append(f"[Section: {heading_path}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_markdown(
    markdown: str,
    doc_title: str,
    doc_id: str = "",
    source_path: str = "",
) -> list[Chunk]:
    """
    Split *markdown* into a list of :class:`Chunk` objects ready for embedding.

    Parameters
    ----------
    markdown:
        Raw markdown text (may include YAML frontmatter).
    doc_title:
        Human-readable document title embedded into every chunk header.
    doc_id:
        Opaque identifier for the document (stored on each chunk).
    source_path:
        Filesystem or URL path of the source file (stored on each chunk).

    Returns
    -------
    list[Chunk]
        Ordered list of chunks, each with sequential ``chunk_index`` values.
        Returns an empty list if the document has no usable content.
    """
    body = _strip_frontmatter(markdown).strip()
    if not body:
        return []

    # Step 1: structural split on headings
    sections = _split_into_sections(body)

    # Step 2: merge tiny adjacent sections
    sections = _merge_small_sections(sections)

    # Step 3: build final chunk list
    chunks: list[Chunk] = []
    for heading_path, text in sections:
        if not text.strip():
            continue

        if len(text) > LARGE_SECTION_CHARS:
            sub_texts = _subdivide(text)
        else:
            sub_texts = [text]

        for sub_text in sub_texts:
            sub_text = sub_text.strip()
            if not sub_text:
                continue
            header = _make_header(doc_title, heading_path)
            full_text = f"{header}\n\n{sub_text}"
            chunks.append(
                Chunk(
                    text=full_text,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    heading_path=heading_path,
                    chunk_index=len(chunks),
                    source_path=source_path,
                )
            )

    return chunks
