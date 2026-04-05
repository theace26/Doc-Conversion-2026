"""
vCard (.vcf) format handler — contact file extraction.

Ingest:
  Parses one or more vCard entries from a .vcf file, extracting
  FN, TEL, EMAIL, ORG, TITLE, and ADR fields.

Export:
  Not supported — raises NotImplementedError.
"""

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

# Fields we extract from each vCard
_FIELDS = ["FN", "TEL", "EMAIL", "ORG", "TITLE", "ADR"]

_FIELD_LABELS = {
    "FN": "Name",
    "TEL": "Phone",
    "EMAIL": "Email",
    "ORG": "Organization",
    "TITLE": "Title",
    "ADR": "Address",
}


def _detect_encoding(file_path: Path) -> str:
    raw = file_path.read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _parse_vcards(text: str) -> list[dict[str, list[str]]]:
    """Parse text into a list of vCard dicts.

    Each dict maps field names (e.g. "FN", "TEL") to lists of values,
    since a contact can have multiple phone numbers, emails, etc.
    """
    cards: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None

    for line in text.splitlines():
        line = line.strip()

        if line.upper() == "BEGIN:VCARD":
            current = {}
            continue

        if line.upper() == "END:VCARD":
            if current is not None:
                cards.append(current)
            current = None
            continue

        if current is None:
            continue

        # Lines look like FIELD;params:value  or  FIELD:value
        m = re.match(r"^([A-Za-z\-]+)(?:;[^:]*)?:(.*)", line)
        if m:
            field_name = m.group(1).upper()
            value = m.group(2).strip()
            if field_name in _FIELDS and value:
                # ADR uses semicolons as separators — join with ", "
                if field_name == "ADR":
                    value = ", ".join(
                        part.strip() for part in value.split(";") if part.strip()
                    )
                current.setdefault(field_name, []).append(value)

    return cards


@register_handler
class VcfHandler(FormatHandler):
    """vCard (.vcf) contact file handler."""

    EXTENSIONS = ["vcf"]

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
            model.warnings.append("Empty vCard file.")
            return model

        cards = _parse_vcards(text)

        if not cards:
            model.warnings.append("No valid vCard entries found.")
            return model

        # H1: use filename if single contact, "Contacts" if multiple
        if len(cards) == 1:
            name = cards[0].get("FN", ["Unknown"])[0]
            model.add_element(Element(
                type=ElementType.HEADING,
                content=name,
                level=1,
            ))
        else:
            model.add_element(Element(
                type=ElementType.HEADING,
                content="Contacts",
                level=1,
            ))

        # Summary
        model.add_element(Element(
            type=ElementType.PARAGRAPH,
            content=f"**Total contacts:** {len(cards)}",
        ))

        # Each contact
        for card in cards:
            name = card.get("FN", ["Unknown"])[0]
            model.add_element(Element(
                type=ElementType.HEADING,
                content=name,
                level=2,
            ))

            details: list[str] = []
            for field_key in _FIELDS:
                if field_key == "FN":
                    continue  # already used as heading
                values = card.get(field_key, [])
                if values:
                    label = _FIELD_LABELS[field_key]
                    for v in values:
                        details.append(f"**{label}:** {v}")

            if details:
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content="\n".join(details),
                ))

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
        )
        return model

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        raise NotImplementedError("Export is not supported for vCard files.")

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {}
