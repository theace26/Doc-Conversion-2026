"""
YAML format handler — YAML/YML data extraction.

Ingest:
  Parses YAML (single or multi-document), produces summary + structure
  outline + verbatim source. Supports comments preservation in source block.

Export:
  Extracts fenced YAML code block and writes verbatim.
"""

import re
import time
from pathlib import Path
from typing import Any

import yaml
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
    lines: list[str] = []
    prefix = "  " * indent

    if isinstance(obj, dict):
        for key, value in obj.items():
            str_key = str(key)
            if isinstance(value, dict):
                lines.append(f"{prefix}- **{str_key}** (object)")
                lines.extend(_build_structure(value, indent + 1, str_key))
            elif isinstance(value, list):
                lines.append(f"{prefix}- **{str_key}** (array, {len(value)} items)")
                lines.extend(_build_array_summary(value, indent + 1, str_key))
            else:
                lines.append(f"{prefix}- **{str_key}** — {_format_value(value, str_key)}")
    elif isinstance(obj, list):
        lines.extend(_build_array_summary(obj, indent, parent_key))

    return lines


def _build_array_summary(arr: list, indent: int, parent_key: str = "") -> list[str]:
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
class YamlHandler(FormatHandler):
    """YAML/YML data file handler."""

    EXTENSIONS = ["yaml", "yml"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="yaml")

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=file_path.suffix.lower().lstrip("."),
        )

        encoding = _detect_encoding(file_path)
        text = file_path.read_text(encoding=encoding, errors="replace")

        if not text.strip():
            model.warnings.append("Empty YAML file.")
            return model

        # Check for multi-document YAML
        is_multi = bool(re.search(r"^---\s*$", text, re.MULTILINE))
        documents: list[Any] = []

        try:
            if is_multi:
                documents = list(yaml.safe_load_all(text))
                # Filter out None documents (empty docs between ---)
                documents = [d for d in documents if d is not None]
            else:
                data = yaml.safe_load(text)
                if data is not None:
                    documents = [data]
        except yaml.YAMLError as exc:
            log.warning("yaml_parse_error", filename=file_path.name, error=str(exc))
            model.warnings.append(f"YAML parse error: {exc}")
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

        if not documents:
            model.warnings.append("YAML file parsed but contained no data.")
            return model

        # Summary
        if len(documents) == 1:
            data = documents[0]
            if isinstance(data, dict):
                type_desc = f"YAML object with {len(data)} top-level keys"
                top_keys = ", ".join(f"`{k}`" for k in list(data.keys())[:20])
            elif isinstance(data, list):
                type_desc = f"YAML array with {len(data)} items"
                top_keys = ""
            else:
                type_desc = f"YAML scalar ({type(data).__name__})"
                top_keys = ""
            depth = _measure_depth(data)
            total_keys = _count_keys(data)
        else:
            type_desc = f"Multi-document YAML with {len(documents)} documents"
            top_keys = ""
            depth = max(_measure_depth(d) for d in documents)
            total_keys = sum(_count_keys(d) for d in documents)

        summary_lines = [f"**Type:** {type_desc}"]
        if top_keys:
            summary_lines.append(f"**Top-level keys:** {top_keys}")
        summary_lines.append(f"**Depth:** {depth} levels")
        summary_lines.append(f"**Total keys:** {total_keys}")

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
        if len(documents) == 1:
            model.add_element(Element(
                type=ElementType.HEADING, content="Structure", level=2,
            ))
            structure_lines = _build_structure(documents[0])
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(structure_lines) if structure_lines else "(empty)",
            ))
        else:
            for i, doc in enumerate(documents):
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=f"Document {i + 1}",
                    level=2,
                ))
                structure_lines = _build_structure(doc)
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content="\n".join(structure_lines) if structure_lines else "(empty)",
                ))

        # Source — preserve original verbatim (keeps comments, anchors, formatting)
        model.add_element(Element(
            type=ElementType.HEADING, content="Source", level=2,
        ))
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=text.rstrip(),
            attributes={"language": "yaml"},
        ))

        model.metadata.page_count = 1
        model.style_data["yaml_encoding"] = encoding
        model.style_data["yaml_multi_document"] = len(documents) > 1

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
        log.info("handler_export_start", filename=output_path.name, target_format="yaml", tier=1)

        # Find fenced YAML code block — write verbatim to preserve comments
        code_blocks = model.get_elements_by_type(ElementType.CODE_BLOCK)
        yaml_text = None
        for block in code_blocks:
            if block.attributes.get("language") == "yaml":
                yaml_text = block.content
                break

        if yaml_text is not None:
            output = yaml_text if yaml_text.endswith("\n") else yaml_text + "\n"
        else:
            # Fallback: try to reconstruct from structure
            paragraphs = model.get_elements_by_type(ElementType.PARAGRAPH)
            combined = "\n".join(p.content for p in paragraphs)
            try:
                data = yaml.safe_load(combined)
                output = yaml.dump(data, default_flow_style=False, allow_unicode=True)
            except yaml.YAMLError:
                output = combined + "\n"

        output_path.write_text(output, encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        encoding = _detect_encoding(file_path)
        raw = file_path.read_text(encoding=encoding, errors="replace")

        has_comments = bool(re.search(r"^\s*#", raw, re.MULTILINE))
        is_multi = bool(re.search(r"^---\s*$", raw, re.MULTILINE))
        doc_count = 1
        if is_multi:
            try:
                docs = list(yaml.safe_load_all(raw))
                doc_count = len([d for d in docs if d is not None])
            except yaml.YAMLError:
                pass

        return {
            "document_level": {
                "extension": file_path.suffix.lower(),
                "encoding": encoding,
                "has_comments": has_comments,
                "multi_document": is_multi,
                "document_count": doc_count,
                "trailing_newline": raw.endswith("\n"),
                "font_family": "monospace",
                "font_name": "Courier New",
            }
        }
