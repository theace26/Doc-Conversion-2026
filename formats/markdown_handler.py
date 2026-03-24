"""
Markdown format handler — DocumentModel ↔ Markdown string conversion.

MarkdownHandler.export(model) → str:
  Converts DocumentModel to full Markdown with YAML frontmatter.
  Handles: headings, paragraphs, tables (pipe syntax), images, lists,
  code blocks, blockquotes, horizontal rules, footnotes.

MarkdownHandler.ingest(md_string) → DocumentModel:
  Parses Markdown back to DocumentModel using mistune.
  Splits YAML frontmatter before parsing content.
"""

from pathlib import Path
from typing import Any

from formats.base import FormatHandler, register_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
    compute_content_hash,
)
from core.metadata import generate_frontmatter, parse_frontmatter


# ── Export helpers ─────────────────────────────────────────────────────────────

def _escape_pipe(text: str) -> str:
    """Escape pipe characters in table cells."""
    return str(text).replace("|", "\\|")


def _render_element(elem: Element, footnotes: list[tuple[str, str]]) -> str:
    """Recursively render a single Element to a Markdown string."""
    t = elem.type

    if t == ElementType.HEADING:
        level = min(max(elem.level or 1, 1), 6)
        return "#" * level + " " + str(elem.content)

    if t == ElementType.PARAGRAPH:
        return str(elem.content) if elem.content else ""

    if t == ElementType.CODE_BLOCK:
        lang = elem.attributes.get("language", "")
        return f"```{lang}\n{elem.content}\n```"

    if t == ElementType.BLOCKQUOTE:
        lines = str(elem.content).splitlines()
        return "\n".join(f"> {line}" for line in lines)

    if t == ElementType.HORIZONTAL_RULE:
        return "---"

    if t == ElementType.PAGE_BREAK:
        return "<!-- pagebreak -->"

    if t == ElementType.IMAGE:
        alt = elem.attributes.get("alt", "image")
        src = elem.attributes.get("src", "")
        width = elem.attributes.get("width")
        height = elem.attributes.get("height")
        if width and height:
            return f'![{alt}]({src} "{width}x{height}")'
        return f"![{alt}]({src})"

    if t == ElementType.LIST:
        return _render_list(elem, footnotes)

    if t == ElementType.LIST_ITEM:
        ordered = elem.attributes.get("ordered", False)
        marker = "1." if ordered else "-"
        text = str(elem.content)
        lines = [f"{marker} {text}"]
        if elem.children:
            for child in elem.children:
                child_text = _render_element(child, footnotes)
                lines.append("  " + child_text)
        return "\n".join(lines)

    if t == ElementType.TABLE:
        return _render_table(elem)

    if t == ElementType.FOOTNOTE:
        fn_id = elem.attributes.get("id", str(len(footnotes) + 1))
        footnotes.append((fn_id, str(elem.content)))
        return f"[^{fn_id}]"

    if t == ElementType.RAW_HTML:
        return str(elem.content)

    return str(elem.content)


def _render_list(elem: Element, footnotes: list[tuple[str, str]]) -> str:
    """Render a LIST element with its children."""
    if not elem.children:
        return ""
    ordered = elem.attributes.get("ordered", False)
    lines = []
    for i, child in enumerate(elem.children, start=1):
        marker = f"{i}." if ordered else "-"
        text = str(child.content)
        lines.append(f"{marker} {text}")
        # Nested list
        if child.children:
            for sub in child.children:
                sub_text = _render_element(sub, footnotes)
                for sub_line in sub_text.splitlines():
                    lines.append("  " + sub_line)
    return "\n".join(lines)


def _render_table(elem: Element) -> str:
    """Render a TABLE element to pipe-syntax Markdown."""
    rows = elem.content if isinstance(elem.content, list) else []
    if not rows:
        return ""

    # First row is the header
    header = rows[0]
    sep = ["-" * max(len(str(cell)), 3) for cell in header]
    lines = [
        "| " + " | ".join(_escape_pipe(str(c)) for c in header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows[1:]:
        # Pad row to match header width
        padded = list(row) + [""] * max(0, len(header) - len(row))
        lines.append("| " + " | ".join(_escape_pipe(str(c)) for c in padded) + " |")
    return "\n".join(lines)


# ── Ingest helpers ─────────────────────────────────────────────────────────────

def _extract_text(node: dict) -> str:
    """Recursively extract plain text from a mistune AST node."""
    if node.get("type") == "text":
        return node.get("raw", "")
    children = node.get("children") or []
    return "".join(_extract_text(c) for c in children)


def _extract_formatted_text(node: dict) -> str:
    """
    Extract text from a mistune AST node, preserving inline markdown markers.

    bold → **text**, italic → *text*, code span → `text`
    Used for PARAGRAPH elements so inline formatting survives the round-trip
    DOCX → Markdown → DOCX.
    """
    ntype = node.get("type", "")
    if ntype == "text":
        return node.get("raw", "")
    if ntype in ("softline_break", "linebreak"):
        return " "
    if ntype == "codespan":
        return f"`{node.get('raw', '')}`"
    if ntype == "strong":
        inner = "".join(_extract_formatted_text(c) for c in (node.get("children") or []))
        return f"**{inner}**"
    if ntype == "emphasis":
        inner = "".join(_extract_formatted_text(c) for c in (node.get("children") or []))
        return f"*{inner}*"
    # All other node types: recurse
    children = node.get("children") or []
    return "".join(_extract_formatted_text(c) for c in children)


def _ast_to_elements(nodes: list[dict]) -> list[Element]:
    """Convert a mistune v3 AST node list to Element objects."""
    elements: list[Element] = []
    footnote_defs: dict[str, str] = {}

    for node in nodes:
        ntype = node.get("type", "")

        if ntype == "heading":
            level = node.get("attrs", {}).get("level", 1)
            text = _extract_text(node)
            elements.append(Element(
                type=ElementType.HEADING,
                content=text,
                level=level,
            ))

        elif ntype == "paragraph":
            # Check if paragraph contains only an image
            children = node.get("children") or []
            if len(children) == 1 and children[0].get("type") == "image":
                img = children[0]
                attrs = img.get("attrs", {})
                elements.append(Element(
                    type=ElementType.IMAGE,
                    content="",
                    attributes={
                        "src": attrs.get("url", ""),
                        "alt": attrs.get("alt", ""),
                        "title": attrs.get("title", ""),
                    },
                ))
            else:
                # Use formatted extraction to preserve **bold**, *italic*, `code`
                text = _extract_formatted_text(node)
                if text.strip():
                    elements.append(Element(
                        type=ElementType.PARAGRAPH,
                        content=text,
                    ))

        elif ntype == "block_code":
            attrs = node.get("attrs", {})
            elements.append(Element(
                type=ElementType.CODE_BLOCK,
                content=node.get("raw", ""),
                attributes={"language": attrs.get("info", "") or ""},
            ))

        elif ntype == "block_quote":
            children = node.get("children") or []
            text = " ".join(_extract_text(c) for c in children).strip()
            elements.append(Element(
                type=ElementType.BLOCKQUOTE,
                content=text,
            ))

        elif ntype == "thematic_break":
            elements.append(Element(type=ElementType.HORIZONTAL_RULE, content=""))

        elif ntype == "list":
            ordered = node.get("attrs", {}).get("ordered", False)
            items = []
            for item in (node.get("children") or []):
                item_text = _extract_text(item)
                items.append(Element(
                    type=ElementType.LIST_ITEM,
                    content=item_text,
                    attributes={"ordered": ordered},
                ))
            elements.append(Element(
                type=ElementType.LIST,
                content="",
                attributes={"ordered": ordered},
                children=items,
            ))

        elif ntype == "table":
            rows: list[list[str]] = []
            head = node.get("children", [{}])[0] if node.get("children") else {}
            body = node.get("children", [{}])[1] if len(node.get("children", [])) > 1 else {}

            # Header row
            if head:
                header_row = []
                for cell in (head.get("children") or []):
                    header_row.append(_extract_text(cell))
                if header_row:
                    rows.append(header_row)

            # Body rows
            for body_row_node in (body.get("children") or []):
                row = []
                for cell in (body_row_node.get("children") or []):
                    row.append(_extract_text(cell))
                if row:
                    rows.append(row)

            if rows:
                elements.append(Element(
                    type=ElementType.TABLE,
                    content=rows,
                ))

        elif ntype == "block_html":
            raw = node.get("raw", "").strip()
            if raw == "<!-- pagebreak -->":
                elements.append(Element(type=ElementType.PAGE_BREAK, content=""))
            elif raw:
                elements.append(Element(type=ElementType.RAW_HTML, content=raw))

        # footnote definitions (mistune v3 emits these separately)
        elif ntype == "footnote_item":
            fn_key = node.get("key") or node.get("label", "")
            fn_text = " ".join(_extract_text(c) for c in (node.get("children") or []))
            footnote_defs[fn_key] = fn_text

    # Append collected footnote definitions as FOOTNOTE elements
    for fn_id, fn_text in footnote_defs.items():
        elements.append(Element(
            type=ElementType.FOOTNOTE,
            content=fn_text,
            attributes={"id": fn_id},
        ))

    return elements


# ── Handler ────────────────────────────────────────────────────────────────────

@register_handler
class MarkdownHandler(FormatHandler):
    """Converts between DocumentModel and Markdown text."""

    EXTENSIONS = ["md", "markdown"]

    # ── Export ────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path | None = None,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,  # ignored; accepted for interface compat
    ) -> str:  # type: ignore[override]
        """
        Convert a DocumentModel to a Markdown string.

        If output_path is provided, also write to that file.
        Always returns the string.
        """
        parts: list[str] = [generate_frontmatter(model)]
        footnotes: list[tuple[str, str]] = []

        prev_type: ElementType | None = None
        for elem in model.elements:
            # Add blank line between certain element transitions for readability
            if prev_type is not None:
                if prev_type in (ElementType.TABLE, ElementType.CODE_BLOCK, ElementType.LIST):
                    parts.append("")
            rendered = _render_element(elem, footnotes)
            if rendered:
                parts.append(rendered)
            prev_type = elem.type

        # Append footnote definitions at end
        if footnotes:
            parts.append("")
            for fn_id, fn_text in footnotes:
                parts.append(f"[^{fn_id}]: {fn_text}")

        # Join with double newlines between elements
        md_text = "\n\n".join(p for p in parts if p is not None)
        if not md_text.endswith("\n"):
            md_text += "\n"

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(md_text, encoding="utf-8")

        return md_text

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        """Read a .md file and return a DocumentModel."""
        text = Path(file_path).read_text(encoding="utf-8")
        return self._ingest_text(text)

    def ingest_text(self, md_text: str) -> DocumentModel:
        """Parse a Markdown string into a DocumentModel (public alias)."""
        return self._ingest_text(md_text)

    def _ingest_text(self, md_text: str) -> DocumentModel:
        import mistune

        fm_dict, body = parse_frontmatter(md_text)

        model = DocumentModel()

        # Populate metadata from frontmatter
        mf = fm_dict.get("markflow", {})
        if mf:
            model.metadata = DocumentMetadata(
                source_file=mf.get("source_file", ""),
                source_format=mf.get("source_format", ""),
                converted_at=mf.get("converted_at", ""),
                markflow_version=mf.get("markflow_version", "0.1.0"),
                ocr_applied=mf.get("ocr_applied", False),
                style_ref=mf.get("style_ref", ""),
                original_preserved=mf.get("original_preserved", False),
                fidelity_tier=mf.get("fidelity_tier", 1),
                title=fm_dict.get("title", ""),
                author=fm_dict.get("author", ""),
                subject=fm_dict.get("subject", ""),
            )

        # Parse Markdown body with mistune AST renderer
        try:
            # mistune v3: tables and strikethrough require explicit plugins
            md_parser = mistune.create_markdown(
                renderer=None,
                plugins=["table", "strikethrough", "footnotes"],
            )
            ast = md_parser(body) or []
        except Exception:
            # Minimal fallback: treat entire body as a single paragraph
            if body.strip():
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content=body.strip(),
                ))
            return model

        for elem in _ast_to_elements(ast):
            model.add_element(elem)

        return model

    # ── extract_styles (not meaningful for Markdown) ─────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """Markdown has no style metadata — returns empty structure."""
        return {"document_level": {}}
