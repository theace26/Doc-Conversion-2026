"""
Format-agnostic intermediate representation (DocumentModel).

All format handlers convert to/from DocumentModel, reducing N×M converters
to N+M. The model carries style metadata natively and uses content-hash
keying for sidecar anchoring so minor Markdown edits don't invalidate styles.
"""

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Element types ─────────────────────────────────────────────────────────────

class ElementType(Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"
    LIST = "list"
    LIST_ITEM = "list_item"
    CODE_BLOCK = "code_block"
    BLOCKQUOTE = "blockquote"
    HORIZONTAL_RULE = "hr"
    PAGE_BREAK = "page_break"
    FOOTNOTE = "footnote"
    RAW_HTML = "raw_html"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ImageData:
    """Binary image data with metadata."""
    data: bytes
    original_format: str          # e.g., "png", "jpeg", "emf"
    width: int | None = None
    height: int | None = None
    alt_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata (not binary data) to dict."""
        return {
            "original_format": self.original_format,
            "width": self.width,
            "height": self.height,
            "alt_text": self.alt_text,
        }


@dataclass
class DocumentMetadata:
    """Source file information and conversion parameters."""
    source_file: str = ""
    source_format: str = ""
    converted_at: str = ""
    markflow_version: str = "0.1.0"
    ocr_applied: bool = False
    style_ref: str = ""
    original_preserved: bool = False
    fidelity_tier: int = 1
    title: str = ""
    author: str = ""
    subject: str = ""
    page_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_format": self.source_format,
            "converted_at": self.converted_at,
            "markflow_version": self.markflow_version,
            "ocr_applied": self.ocr_applied,
            "style_ref": self.style_ref,
            "original_preserved": self.original_preserved,
            "fidelity_tier": self.fidelity_tier,
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "page_count": self.page_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentMetadata":
        valid = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class Element:
    """A single content element in the document."""
    type: ElementType
    content: str | list = ""          # str for text; list[list[str]] for table rows
    level: int | None = None          # heading level or list nesting depth
    content_hash: str = ""            # SHA-256[:16] of normalized content
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list["Element"] | None = None

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = compute_content_hash(self.content)

    def to_dict(self) -> dict[str, Any]:
        def _serialize_content(c: str | list) -> str | list:
            if not isinstance(c, list):
                return c
            return [[str(cell) for cell in row] for row in c]

        return {
            "type": self.type.value,
            "content": _serialize_content(self.content),
            "level": self.level,
            "content_hash": self.content_hash,
            "attributes": self.attributes,
            "children": [ch.to_dict() for ch in self.children] if self.children else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Element":
        elem_type = ElementType(d["type"])
        children = [cls.from_dict(c) for c in d["children"]] if d.get("children") else None
        return cls(
            type=elem_type,
            content=d.get("content", ""),
            level=d.get("level"),
            content_hash=d.get("content_hash", ""),
            attributes=d.get("attributes", {}),
            children=children,
        )


@dataclass
class DocumentModel:
    """Format-agnostic intermediate representation."""
    elements: list[Element] = field(default_factory=list)
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    style_data: dict[str, Any] = field(default_factory=dict)
    images: dict[str, ImageData] = field(default_factory=dict)  # hash_filename → ImageData
    warnings: list[str] = field(default_factory=list)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def add_element(self, element: Element) -> None:
        """Append an element to the document."""
        self.elements.append(element)

    def get_elements_by_type(self, element_type: ElementType) -> list[Element]:
        """Return all top-level elements of a given type."""
        return [e for e in self.elements if e.type == element_type]

    def to_markdown(self) -> str:
        """Convert to Markdown string (uses MarkdownHandler)."""
        from formats.markdown_handler import MarkdownHandler
        return MarkdownHandler().export(self)

    @classmethod
    def from_markdown(cls, md_text: str) -> "DocumentModel":
        """Parse Markdown text into a DocumentModel (uses MarkdownHandler)."""
        from formats.markdown_handler import MarkdownHandler
        return MarkdownHandler().ingest_text(md_text)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "elements": [e.to_dict() for e in self.elements],
            "metadata": self.metadata.to_dict(),
            "style_data": self.style_data,
            "images": {k: v.to_dict() for k, v in self.images.items()},
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentModel":
        model = cls()
        model.elements = [Element.from_dict(e) for e in d.get("elements", [])]
        model.metadata = DocumentMetadata.from_dict(d.get("metadata", {}))
        model.style_data = d.get("style_data", {})
        model.warnings = d.get("warnings", [])
        # Binary image data is not restored from dict (use the filesystem)
        return model


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_content_hash(content: str | list) -> str:
    """Return SHA-256[:16] of normalized content for sidecar anchoring."""
    if isinstance(content, list):
        # Flatten table rows into a canonical string
        normalized = " | ".join(
            " | ".join(str(cell) for cell in row)
            for row in content
        )
    else:
        # Collapse whitespace, lowercase
        normalized = re.sub(r"\s+", " ", str(content)).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
