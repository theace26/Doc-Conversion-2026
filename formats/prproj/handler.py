"""Premiere Pro project (.prproj) deep handler.

Renders a structured Markdown summary that lists project metadata, the
bin tree, every sequence, and every referenced media file (grouped by
type). The Markdown is what Meilisearch indexes — so a search for a
clip filename surfaces every Premiere project that references it, even
without the Phase 2 cross-reference table.

Routing wins over :class:`formats.adobe_handler.AdobeHandler` because
``formats/__init__.py`` imports this module **after** ``adobe_handler``
and the registry's last-writer-wins behaviour replaces the entry for
``"prproj"``. ``adobe_handler.EXTENSIONS`` also drops ``"prproj"`` as a
defensive belt-and-braces.

Phase 2 hook: after a successful deep-parse, the handler also calls
:func:`core.db.prproj_refs.upsert_media_refs` so the cross-reference
endpoints have data. The DB write is wrapped in try/except so a DB
blip never fails a conversion.

Author: v0.34.0 Phase 1.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)
from formats.base import FormatHandler, register_handler
from formats.prproj.parser import (
    PrprojDocument,
    empty_document,
    parse_prproj,
)

log = structlog.get_logger(__name__)


@register_handler
class PrprojHandler(FormatHandler):
    """Handler for Premiere Pro project files (.prproj)."""

    EXTENSIONS = ["prproj"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        log.info("handler_ingest_start", filename=file_path.name, format="prproj")

        try:
            doc = parse_prproj(file_path)
        except Exception as exc:  # noqa: BLE001 — operational fallback
            log.warning(
                "prproj.deep_parse_failed",
                path=str(file_path),
                error_class=exc.__class__.__name__,
                error=str(exc),
            )
            doc = empty_document(file_path.stem, reason=exc.__class__.__name__)

        model = self._render(doc, file_path)

        # Phase 2 hook: persist the media-refs cross-reference. Wrapped so a
        # DB outage never fails the conversion. The hook only fires when
        # we got at least one ref out — empty-document fallbacks skip it.
        if doc.media:
            self._best_effort_persist_refs(doc, file_path)

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "handler_ingest_complete",
            filename=file_path.name,
            element_count=len(model.elements),
            duration_ms=duration_ms,
            schema_confidence=doc.schema_confidence,
            n_media=len(doc.media),
            n_sequences=len(doc.sequences),
        )
        return model

    # ── Markdown rendering ────────────────────────────────────────────────────

    def _render(self, doc: PrprojDocument, file_path: Path) -> DocumentModel:
        """Build a DocumentModel from a parsed PrprojDocument."""
        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format="prproj",
            title=doc.project_name,
        )

        # H1: project name
        model.add_element(Element(
            type=ElementType.HEADING,
            content=doc.project_name,
            level=1,
        ))

        # ── Project metadata table ──
        meta_rows: list[list[str]] = [["Field", "Value"]]
        meta_rows.append(["Project file", file_path.name])
        if doc.schema_version and doc.schema_version != "unknown":
            meta_rows.append(["Premiere version", doc.schema_version])
        for key, label in (
            ("FrameRate", "Frame rate"),
            ("VideoFrameRate", "Frame rate"),
            ("AudioSampleRate", "Audio sample rate"),
            ("WorkingColorSpace", "Color space"),
            ("Title", "Title"),
        ):
            v = doc.project_settings.get(key)
            if v and not any(row[0] == label for row in meta_rows[1:]):
                meta_rows.append([label, str(v)])
        meta_rows.append([
            "Schema confidence",
            doc.schema_confidence,
        ])
        meta_rows.append([
            "Element count",
            f"{doc.raw_element_count:,}" if doc.raw_element_count else "0",
        ])
        meta_rows.append([
            "Indexed at",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ])

        if len(meta_rows) > 1:
            model.add_element(Element(
                type=ElementType.TABLE,
                content=meta_rows,
                attributes={"role": "metadata_summary"},
            ))

        # ── Sequences ──
        if doc.sequences:
            model.add_element(Element(
                type=ElementType.HEADING,
                content=f"Sequence{'s' if len(doc.sequences) != 1 else ''} ({len(doc.sequences)})",
                level=2,
            ))
            seq_rows: list[list[str]] = [
                ["Name", "Duration", "Resolution", "Clips", "Markers"],
            ]
            for seq in doc.sequences:
                seq_rows.append([
                    seq.name or seq.seq_id,
                    _format_duration(seq.duration_ticks, seq.frame_rate),
                    _format_resolution(seq.width, seq.height),
                    str(seq.clip_count) if seq.clip_count is not None else "—",
                    str(seq.marker_count) if seq.marker_count is not None else "—",
                ])
            model.add_element(Element(
                type=ElementType.TABLE,
                content=seq_rows,
                attributes={"role": "sequence_list"},
            ))

        # ── Media (grouped by type) ──
        if doc.media:
            model.add_element(Element(
                type=ElementType.HEADING,
                content=f"Media ({len(doc.media)} master clip{'s' if len(doc.media) != 1 else ''})",
                level=2,
            ))
            grouped: dict[str, list] = {}
            for ref in doc.media:
                grouped.setdefault(ref.media_type, []).append(ref)
            type_order = ("video", "audio", "image", "graphic", "unknown")
            for media_type in type_order:
                refs = grouped.get(media_type)
                if not refs:
                    continue
                model.add_element(Element(
                    type=ElementType.HEADING,
                    content=f"{media_type.title()} ({len(refs)})",
                    level=3,
                ))
                # The Markdown export pipeline turns a paragraph element with
                # newline-separated lines into a paragraph in the output. To
                # produce a list-shaped block of references that searches well,
                # render one ref per paragraph — keeps clip filenames on their
                # own lines, and Meilisearch tokenization treats them
                # identically.
                lines = []
                for ref in refs:
                    lines.append(f"- `{ref.path}` — {ref.name}")
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content="\n".join(lines),
                    attributes={"role": "media_list", "media_type": media_type},
                ))

        # ── Bin tree ──
        if doc.bins:
            model.add_element(Element(
                type=ElementType.HEADING,
                content=f"Bin tree ({len(doc.bins)} bin{'s' if len(doc.bins) != 1 else ''})",
                level=2,
            ))
            tree_lines = _build_bin_tree(doc.bins)
            if tree_lines:
                model.add_element(Element(
                    type=ElementType.CODE_BLOCK,
                    content="\n".join(tree_lines),
                    attributes={"language": "text"},
                ))

        # ── Parse warnings (operator-visible) ──
        if doc.parse_warnings:
            model.add_element(Element(
                type=ElementType.HEADING,
                content=f"Parse warning{'s' if len(doc.parse_warnings) != 1 else ''} ({len(doc.parse_warnings)})",
                level=2,
            ))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(f"- {w}" for w in doc.parse_warnings),
                attributes={"role": "parse_warnings"},
            ))

        # Stash structured data for any downstream consumer that wants it.
        model.style_data["prproj"] = {
            "schema_confidence": doc.schema_confidence,
            "schema_version": doc.schema_version,
            "media_count": len(doc.media),
            "sequence_count": len(doc.sequences),
            "bin_count": len(doc.bins),
            "raw_element_count": doc.raw_element_count,
        }
        model.metadata.page_count = 1
        return model

    # ── Phase 2 cross-reference hook ──────────────────────────────────────────

    def _best_effort_persist_refs(
        self, doc: PrprojDocument, file_path: Path
    ) -> None:
        """Fire-and-forget upsert of media refs. Never raises into ingest."""
        try:
            from core.db.prproj_refs import upsert_media_refs_sync
        except Exception as exc:  # noqa: BLE001
            log.debug("prproj.refs_module_unavailable", error=str(exc))
            return

        try:
            n = upsert_media_refs_sync(
                project_path=str(file_path),
                refs=[
                    {
                        "media_path": ref.path,
                        "media_name": ref.name,
                        "media_type": ref.media_type,
                        "duration_ticks": ref.duration_ticks,
                    }
                    for ref in doc.media
                ],
            )
            log.info(
                "prproj.media_ref_recorded",
                project_path=str(file_path),
                n_refs=n,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "prproj.media_ref_record_failed",
                project_path=str(file_path),
                error_class=exc.__class__.__name__,
                error=str(exc),
            )

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        """Write the rendered DocumentModel as Markdown.

        Premiere can't be authored from Markdown, so the export shape is
        the same Markdown the search index sees.
        """
        target_ext = output_path.suffix.lower().lstrip(".")
        log.info(
            "handler_export_start",
            filename=output_path.name,
            target_format=target_ext,
            tier=1,
        )

        lines: list[str] = []
        for elem in model.elements:
            if elem.type == ElementType.HEADING:
                prefix = "#" * (elem.level or 1)
                lines.append(f"{prefix} {elem.content}")
                lines.append("")
            elif elem.type == ElementType.PARAGRAPH:
                lines.append(elem.content)
                lines.append("")
            elif elem.type == ElementType.TABLE:
                rows = elem.content
                if isinstance(rows, list) and rows:
                    header = rows[0]
                    body = rows[1:] if len(rows) > 1 else []
                    if isinstance(header, list):
                        lines.append("| " + " | ".join(str(c) for c in header) + " |")
                        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                    for row in body:
                        if isinstance(row, list):
                            lines.append("| " + " | ".join(str(c) for c in row) + " |")
                    lines.append("")
            elif elem.type == ElementType.CODE_BLOCK:
                lang = (elem.attributes or {}).get("language", "")
                lines.append(f"```{lang}".rstrip())
                lines.append(str(elem.content))
                lines.append("```")
                lines.append("")
            elif elem.type == ElementType.HORIZONTAL_RULE:
                lines.append("---")
                lines.append("")

        if target_ext not in ("md", "markdown"):
            lines.insert(0,
                f"<!-- MarkFlow: .prproj content rendered as Markdown ({target_ext} requested). -->\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        log.info("handler_export_complete", filename=output_path.name)

    # ── Style extraction (interface compliance) ───────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """Return minimal style data — Premiere XML carries no font/style
        information that maps cleanly onto the project-wide style schema.
        """
        return {
            "document_level": {
                "extension": ".prproj",
                "fonts": [],
                "metadata": {},
            }
        }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _format_duration(ticks: int | None, frame_rate: float | None) -> str:
    """Convert Premiere's tick count + frame rate into HH:MM:SS-ish text.

    Premiere's tick base varies by version (commonly 254016000000 ticks =
    1 second), so without a confirmed base we fall back to "—" rather than
    rendering a wrong number.
    """
    if not ticks or not frame_rate:
        return "—"
    # Best-effort: Premiere CC uses 254016000000 ticks per second.
    seconds = ticks / 254016000000.0
    if seconds <= 0 or seconds > 24 * 60 * 60:
        return "—"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _format_resolution(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "—"
    return f"{width}×{height}"


def _build_bin_tree(bins: tuple) -> list[str]:
    """Render bins as an ASCII tree under a synthetic ``Root`` node."""
    by_parent: dict[str | None, list] = {}
    for b in bins:
        by_parent.setdefault(b.parent_bin_id, []).append(b)

    lines: list[str] = ["Root"]

    def _walk(parent_id: str | None, prefix: str, is_last: bool) -> None:
        children = by_parent.get(parent_id, [])
        for i, child in enumerate(children):
            last = i == len(children) - 1
            branch = "└── " if last else "├── "
            lines.append(f"{prefix}{branch}{child.name}")
            ext_prefix = prefix + ("    " if last else "│   ")
            _walk(child.bin_id, ext_prefix, last)

    _walk(None, "", True)
    if len(lines) == 1:
        # Bins exist but none had a null parent — render flat.
        for b in bins:
            lines.append(f"  ├── {b.name}")
    return lines
