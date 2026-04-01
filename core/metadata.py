"""
Metadata generation and parsing for MarkFlow output files.

- generate_frontmatter(model) → YAML frontmatter block for .md files
- parse_frontmatter(md_text) → (metadata_dict, content) — splits frontmatter from content
- generate_manifest(batch_id, files) → batch manifest JSON
- generate_sidecar(model, style_data) → style sidecar with schema_version
- load_sidecar(path) → load and validate sidecar, migrate schema_version if needed
"""

import json
import re
from pathlib import Path
from typing import Any

from core.database import now_iso

import yaml

from core.document_model import DocumentModel

SCHEMA_VERSION = "1.0.0"
MARKFLOW_VERSION = "0.1.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}


# ── Frontmatter ───────────────────────────────────────────────────────────────

def generate_frontmatter(model: DocumentModel) -> str:
    """Generate YAML frontmatter block from a DocumentModel's metadata."""
    meta = model.metadata
    data: dict[str, Any] = {
        "markflow": {
            "source_file": meta.source_file,
            "source_format": meta.source_format,
            "converted_at": meta.converted_at or now_iso(),
            "markflow_version": meta.markflow_version,
            "ocr_applied": meta.ocr_applied,
            "style_ref": meta.style_ref or "",
            "original_preserved": meta.original_preserved,
            "fidelity_tier": meta.fidelity_tier,
        }
    }
    if meta.title:
        data["title"] = meta.title
    if meta.author:
        data["author"] = meta.author
    if meta.subject:
        data["subject"] = meta.subject

    return "---\n" + yaml.dump(data, allow_unicode=True, default_flow_style=False) + "---\n\n"


def parse_frontmatter(md_text: str) -> tuple[dict[str, Any], str]:
    """
    Split YAML frontmatter from Markdown body.

    Returns:
        (metadata_dict, body_content)
    """
    if not md_text.startswith("---"):
        return {}, md_text

    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", md_text, re.DOTALL)
    if not match:
        return {}, md_text

    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        metadata = {}

    body = md_text[match.end():]
    return metadata, body


# ── Batch manifest ────────────────────────────────────────────────────────────

def generate_manifest(batch_id: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate batch manifest JSON."""
    success_count = sum(1 for f in files if f.get("status") == "success")
    error_count = sum(1 for f in files if f.get("status") == "error")
    total_duration = sum(f.get("duration_ms", 0) or 0 for f in files)

    return {
        "batch_id": batch_id,
        "created_at": now_iso(),
        "total_files": len(files),
        "success_count": success_count,
        "error_count": error_count,
        "total_duration_ms": total_duration,
        "files": files,
    }


# ── Style sidecar ─────────────────────────────────────────────────────────────

def generate_sidecar(
    model: DocumentModel,
    style_data: dict[str, Any],
) -> dict[str, Any]:
    """Generate style sidecar JSON with schema_version."""
    doc_level = style_data.get("document_level", {})
    elements = {k: v for k, v in style_data.items() if k not in ("document_level", "schema_version")}

    return {
        "schema_version": SCHEMA_VERSION,
        "source_format": model.metadata.source_format,
        "source_file": model.metadata.source_file,
        "converted_at": model.metadata.converted_at or now_iso(),
        "document_level": doc_level,
        "elements": elements,
    }


def load_sidecar(path: Path) -> dict[str, Any]:
    """Load and validate a style sidecar JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("schema_version", "unknown")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        data["_migration_warning"] = (
            f"Sidecar schema version '{version}' is not supported. "
            f"Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    return data


# ── Internal helpers ──────────────────────────────────────────────────────────
