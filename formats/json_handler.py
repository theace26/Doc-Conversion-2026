"""
JSON format handler — structured JSON data extraction.

Ingest:
  Parses JSON, produces summary + structure outline + verbatim source.
  Secret values redacted in structure; long strings truncated.

Export:
  Extracts fenced JSON code block and writes pretty-printed JSON.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import structlog

from formats.base import FormatHandler, register_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)

log = structlog.get_logger(__name__)

_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

_SECRET_KEYS = re.compile(
    r"(password|secret|token|api_key|apikey|credential|auth)", re.IGNORECASE
)

_MAX_STR_LEN = 80
_MAX_ARRAY_SHOW = 10
_MAX_DEPTH_MEASURE = 20


def _detect_encoding(file_path: Path) -> str:
    raw = file_path.read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _measure_depth(obj: Any, current: int = 0) -> int:
    if current >= _MAX_DEPTH_MEASURE:
        return current
    if isinstance(obj, dict):
        if not obj:
            return current + 1
        return max(_measure_depth(v, current + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current + 1
        return max(_measure_depth(v, current + 1) for v in obj)
    return current


def _count_keys(obj: Any) -> int:
    if isinstance(obj, dict):
        return len(obj) + sum(_count_keys(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_keys(v) for v in obj)
    return 0


def _format_value(value: Any, key: str = "") -> str:
    """Format a scalar value for the structure outline."""
    if _SECRET_KEYS.search(key) and isinstance(value, str) and value:
        return f"*(redacted — {len(value)} chars)*"
    if isinstance(value, str):
        if len(value) > _MAX_STR_LEN:
            return f'`"{value[:_MAX_STR_LEN]}…"` ({len(value)} chars)'
        return f'`"{value}"`'
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if value is None:
        return "`null`"
    return f"`{value}`"


def _build_structure(obj: Any, indent: int = 0, parent_key: str = "") -> list[str]:
    """Recursively build a markdown list outlining the JSON structure."""
    lines: list[str] = []
    prefix = "  " * indent

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}- **{key}** (object)")
                lines.extend(_build_structure(value, indent + 1, key))
            elif isinstance(value, list):
                lines.append(f"{prefix}- **{key}** (array, {len(value)} items)")
                lines.extend(_build_array_summary(value, indent + 1, key))
            else:
                lines.append(f"{prefix}- **{key}** — {_format_value(value, key)}")
    elif isinstance(obj, list):
        lines.extend(_build_array_summary(obj, indent, parent_key))

    return lines


def _build_array_summary(arr: list, indent: int, parent_key: str = "") -> list[str]:
    """Summarize array contents for the structure outline."""
    lines: list[str] = []
    prefix = "  " * indent

    if not arr:
        return lines

    if len(arr) <= _MAX_ARRAY_SHOW:
        for i, item in enumerate(arr):
            if isinstance(item, dict):
                lines.append(f"{prefix}- [{i}] (object)")
                lines.extend(_build_structure(item, indent + 1, parent_key))
            elif isinstance(item, list):
                lines.append(f"{prefix}- [{i}] (array, {len(item)} items)")
            else:
                lines.append(f"{prefix}- [{i}] — {_format_value(item, parent_key)}")
    else:
        # Show first 5 and last 2
        for i in range(5):
            item = arr[i]
            if isinstance(item, dict):
                lines.append(f"{prefix}- [{i}] (object)")
                lines.extend(_build_structure(item, indent + 1, parent_key))
            elif isinstance(item, list):
                lines.append(f"{prefix}- [{i}] (array, {len(item)} items)")
            else:
                lines.append(f"{prefix}- [{i}] — {_format_value(item, parent_key)}")

        lines.append(f"{prefix}- *... ({len(arr) - 7} more items)*")

        for i in range(len(arr) - 2, len(arr)):
            item = arr[i]
            if isinstance(item, dict):
                lines.append(f"{prefix}- [{i}] (object)")
            elif isinstance(item, list):
                lines.append(f"{prefix}- [{i}] (array, {len(item)} items)")
            else:
                lines.append(f"{prefix}- [{i}] — {_format_value(item, parent_key)}")

    return lines


@register_handler
class JsonHandler(FormatHandler):
    """JSON data file handler."""

    EXTENSIONS = ["json"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="json")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="json",
        )

        encoding = _detect_encoding(file_path)
        text = file_path.read_text(encoding=encoding, errors="replace")

        if not text.strip():
            model.warnings.append("Empty JSON file.")
            return model

        # Parse
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("json_parse_error", filename=file_path.name, error=str(exc))
            model.warnings.append(f"JSON parse error: {exc}")
            model.style_data["parse_error"] = True
            model.add_element(Element(
                type=ElementType.HEADING, content=f"{file_path.name}", level=1,
            ))
            model.add_element(Element(
                type=ElementType.CODE_BLOCK,
                content=text,
                attributes={"language": "text"},
            ))
            return model

        # Summary
        if isinstance(data, dict):
            type_desc = f"JSON object with {len(data)} top-level keys"
            top_keys = ", ".join(f"`{k}`" for k in list(data.keys())[:20])
        elif isinstance(data, list):
            type_desc = f"JSON array with {len(data)} items"
            top_keys = ""
        else:
            type_desc = f"JSON scalar ({type(data).__name__})"
            top_keys = ""

        depth = _measure_depth(data)
        total_keys = _count_keys(data)

        summary_lines = [f"**Type:** {type_desc}"]
        if top_keys:
            summary_lines.append(f"**Top-level keys:** {top_keys}")
        summary_lines.append(f"**Depth:** {depth} levels")
        summary_lines.append(f"**Total keys:** {total_keys}")

        # Build model elements
        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"{file_path.name} — Summary",
            level=1,
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(summary_lines),
        ))

        # Structure
        model.add_element(Element(
            type=ElementType.HEADING, content="Structure", level=2,
        ))
        structure_lines = _build_structure(data)
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(structure_lines) if structure_lines else "(empty)",
        ))

        # Source
        model.add_element(Element(
            type=ElementType.HEADING, content="Source", level=2,
        ))
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=pretty,
            attributes={"language": "json"},
        ))

        model.metadata.page_count = 1
        model.style_data["json_encoding"] = encoding

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="json", tier=1)

        # Find fenced JSON code block
        code_blocks = model.get_elements_by_type(ElementType.CODE_BLOCK)
        json_text = None
        for block in code_blocks:
            if block.attributes.get("language") == "json":
                json_text = block.content
                break

        if json_text is None:
            # Fallback: collect all paragraph text
            paragraphs = model.get_elements_by_type(ElementType.PARAGRAPH)
            json_text = "\n".join(p.content for p in paragraphs)

        # Validate and pretty-print
        try:
            data = json.loads(json_text)
            output = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        except (json.JSONDecodeError, ValueError):
            output = json_text + "\n"

        output_path.write_text(output, encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        encoding = _detect_encoding(file_path)
        raw = file_path.read_text(encoding=encoding, errors="replace")

        # Detect original indent
        indent = 2
        for line in raw.split("\n")[1:10]:
            stripped = line.lstrip()
            if stripped and line != stripped:
                indent = len(line) - len(stripped)
                break

        # Detect key sorting
        sort_keys = False
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and len(data) > 1:
                keys = list(data.keys())
                sort_keys = keys == sorted(keys)
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "document_level": {
                "extension": ".json",
                "encoding": encoding,
                "indent": indent,
                "trailing_newline": raw.endswith("\n"),
                "sort_keys": sort_keys,
                "font_family": "monospace",
                "font_name": "Courier New",
            }
        }
