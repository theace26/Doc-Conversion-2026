"""
INI/CFG/CONF format handler — config file extraction.

Ingest:
  Parses with configparser (interpolation disabled). Falls back to
  line-by-line section detection for malformed files. Files with .conf
  extension and no [section] headers are treated as plain text.

Export:
  Extracts fenced ini/cfg code block and writes verbatim.
"""

import configparser
import re
import time
from io import StringIO
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

_SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$")


def _detect_encoding(file_path: Path) -> str:
    raw = file_path.read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _redact_value(key: str, value: str) -> str:
    if _SECRET_KEYS.search(key) and value:
        return f"*(redacted — {len(value)} chars)*"
    return f"`{value}`"


@register_handler
class IniHandler(FormatHandler):
    """INI/CFG/CONF/properties config file handler."""

    EXTENSIONS = ["ini", "cfg", "conf", "properties"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        ext = file_path.suffix.lower().lstrip(".")
        log.info("handler_ingest_start", filename=file_path.name, format=ext)

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext,
        )

        encoding = _detect_encoding(file_path)
        text = file_path.read_text(encoding=encoding, errors="replace")

        if not text.strip():
            model.warnings.append("Empty config file.")
            return model

        # Try configparser first
        sections = self._try_configparser(text)

        if sections is None:
            # Fallback: line-by-line section detection
            sections = self._try_line_parse(text)

        # If .conf and no sections found, treat as plain text
        if not sections and ext == "conf":
            log.info("conf_not_ini", filename=file_path.name,
                     msg="File has .conf extension but is not INI format — treating as plain text")
            return self._as_plain_text(file_path, text, model)

        # Even for non-.conf files, if nothing parsed, show as plain text
        if not sections:
            return self._as_plain_text(file_path, text, model)

        # Build summary
        total_keys = sum(len(kvs) for kvs in sections.values())
        section_names = ", ".join(f"`[{s}]`" for s in sections if s != "DEFAULT")
        if "DEFAULT" in sections and sections["DEFAULT"]:
            section_names = "`[DEFAULT]`, " + section_names if section_names else "`[DEFAULT]`"

        summary_lines = [
            f"**Sections:** {len(sections)}",
            f"**Total keys:** {total_keys}",
        ]
        if section_names:
            summary_lines.append(f"**Section names:** {section_names}")

        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"{file_path.name} — Summary",
            level=1,
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content="\n".join(summary_lines),
        ))

        # Structure — one H3 per section
        model.add_element(Element(
            type=ElementType.HEADING, content="Structure", level=2,
        ))

        for section_name, keys in sections.items():
            model.add_element(Element(
                type=ElementType.HEADING,
                content=f"[{section_name}]",
                level=3,
            ))
            if keys:
                lines = []
                for k, v in keys.items():
                    lines.append(f"- **{k}** = {_redact_value(k, v)}")
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content="\n".join(lines),
                ))

        # Source
        model.add_element(Element(
            type=ElementType.HEADING, content="Source", level=2,
        ))
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=text.rstrip(),
            attributes={"language": "ini"},
        ))

        model.metadata.page_count = 1
        model.style_data["ini_encoding"] = encoding

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _try_configparser(self, text: str) -> dict[str, dict[str, str]] | None:
        """Try parsing with configparser. Returns sections dict or None on failure."""
        parser = configparser.ConfigParser(
            interpolation=None,
            comment_prefixes=("#", ";"),
            allow_no_value=True,
        )
        try:
            parser.read_string(text)
        except (configparser.Error, KeyError):
            return None

        sections: dict[str, dict[str, str]] = {}

        # DEFAULT section
        defaults = dict(parser.defaults())
        if defaults:
            sections["DEFAULT"] = defaults

        for section in parser.sections():
            items = {}
            for key, value in parser.items(section):
                # Skip keys inherited from DEFAULT that we already captured
                if key in defaults and defaults[key] == value:
                    continue
                items[key] = value if value is not None else ""
            sections[section] = items

        return sections if sections else None

    def _try_line_parse(self, text: str) -> dict[str, dict[str, str]]:
        """Fallback line-by-line parser for malformed INI files."""
        sections: dict[str, dict[str, str]] = {}
        current_section = "DEFAULT"

        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            section_match = _SECTION_RE.match(line)
            if section_match:
                current_section = section_match.group(1)
                if current_section not in sections:
                    sections[current_section] = {}
                continue

            # Key=value or key:value
            sep_match = re.match(r"^([^=:]+?)\s*[=:]\s*(.*)", line)
            if sep_match:
                key = sep_match.group(1).strip()
                value = sep_match.group(2).strip()
                if current_section not in sections:
                    sections[current_section] = {}
                sections[current_section][key] = value

        return sections

    def _as_plain_text(self, file_path: Path, text: str, model: DocumentModel) -> DocumentModel:
        """Treat file as plain text (for .conf files that aren't INI format)."""
        model.add_element(Element(
            type=ElementType.HEADING,
            content=f"{file_path.name}",
            level=1,
        ))
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content=f"**Type:** Plain text config file ({len(text.splitlines())} lines)",
        ))
        model.add_element(Element(
            type=ElementType.CODE_BLOCK,
            content=text.rstrip(),
            attributes={"language": "text"},
        ))
        model.metadata.page_count = 1
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
        log.info("handler_export_start", filename=output_path.name, target_format="ini", tier=1)

        # Find fenced ini or cfg code block
        code_blocks = model.get_elements_by_type(ElementType.CODE_BLOCK)
        ini_text = None
        for block in code_blocks:
            lang = block.attributes.get("language", "")
            if lang in ("ini", "cfg", "conf", "properties", "text"):
                ini_text = block.content
                break

        if ini_text is not None:
            output = ini_text if ini_text.endswith("\n") else ini_text + "\n"
        else:
            # Reconstruct from structure
            output = self._reconstruct_ini(model)

        output_path.write_text(output, encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    def _reconstruct_ini(self, model: DocumentModel) -> str:
        """Reconstruct INI from model structure (H3 = section, paragraphs = keys)."""
        lines: list[str] = []
        headings = model.get_elements_by_type(ElementType.HEADING)
        paragraphs = model.get_elements_by_type(ElementType.PARAGRAPH)

        for elem in model.elements:
            if elem.type == ElementType.HEADING and elem.level == 3:
                section = elem.content.strip("[]")
                lines.append(f"\n[{section}]")
            elif elem.type == ElementType.PARAGRAPH:
                for line in elem.content.split("\n"):
                    # Parse "- **key** = `value`" format
                    m = re.match(r"^-\s+\*\*(.+?)\*\*\s*=\s*`(.+?)`", line)
                    if m:
                        lines.append(f"{m.group(1)} = {m.group(2)}")

        return "\n".join(lines).strip() + "\n"

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        encoding = _detect_encoding(file_path)
        raw = file_path.read_text(encoding=encoding, errors="replace")

        # Detect comment style
        comment_style = "#"
        hash_count = len(re.findall(r"^\s*#", raw, re.MULTILINE))
        semi_count = len(re.findall(r"^\s*;", raw, re.MULTILINE))
        if semi_count > hash_count:
            comment_style = ";"

        # Check for default section (keys before any [section])
        has_default = False
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if _SECTION_RE.match(line):
                break
            if "=" in line or ":" in line:
                has_default = True
                break

        # Blank lines between sections
        blank_between = bool(re.search(r"\n\n\[", raw))

        return {
            "document_level": {
                "extension": file_path.suffix.lower(),
                "encoding": encoding,
                "comment_style": comment_style,
                "has_default_section": has_default,
                "trailing_newline": raw.endswith("\n"),
                "blank_lines_between_sections": blank_between,
                "font_family": "monospace",
                "font_name": "Courier New",
            }
        }
