"""
Email format handler — EML and MSG files.

Ingest:
  EML: Uses stdlib email module to parse headers and body.
  MSG: Uses compressed_rtf via olefile for Outlook .msg files.
  Extracts subject as heading, headers as metadata, body as paragraphs.
  Recursively converts attachments via the format registry (depth-limited to 3).

Export:
  Generates RFC 5322 compliant .eml from DocumentModel.
"""

import email
import email.policy
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import structlog

from formats.base import FormatHandler, register_handler, get_handler
from core.document_model import (
    DocumentModel,
    DocumentMetadata,
    Element,
    ElementType,
)
from core.storage_probe import ErrorRateMonitor

log = structlog.get_logger(__name__)

_MAX_ATTACHMENT_DEPTH = 3


def _human_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _model_to_markdown_body(model: DocumentModel) -> str:
    """Convert a DocumentModel to markdown text without frontmatter."""
    from formats.markdown_handler import MarkdownHandler, _render_element
    parts: list[str] = []
    footnotes: list[tuple[str, str]] = []
    for elem in model.elements:
        rendered = _render_element(elem, footnotes)
        if rendered is not None:
            parts.append(rendered)
    return "\n\n".join(parts)


@register_handler
class EmlHandler(FormatHandler):
    """Email handler for .eml and .msg files."""

    EXTENSIONS = ["eml", "msg"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path, **kwargs) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        log.info("handler_ingest_start", filename=file_path.name, format=ext.lstrip("."))

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext.lstrip("."),
        )

        depth = kwargs.get("depth", 0)

        if ext == ".msg":
            self._ingest_msg(file_path, model, depth)
        else:
            self._ingest_eml(file_path, model, depth)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _ingest_eml(self, file_path: Path, model: DocumentModel, depth: int = 0) -> None:
        """Parse a standard .eml file."""
        raw = file_path.read_bytes()
        msg = email.message_from_bytes(raw, policy=email.policy.default)

        # Headers
        subject = msg.get("Subject", "")
        from_addr = msg.get("From", "")
        to_addr = msg.get("To", "")
        date = msg.get("Date", "")

        model.metadata.title = subject
        model.metadata.author = from_addr

        # Subject as heading
        if subject:
            model.add_element(Element(
                type=ElementType.HEADING,
                content=subject,
                level=1,
            ))

        # Email headers as metadata paragraph
        headers = []
        if from_addr:
            headers.append(f"From: {from_addr}")
        if to_addr:
            headers.append(f"To: {to_addr}")
        if date:
            headers.append(f"Date: {date}")
        cc = msg.get("Cc", "")
        if cc:
            headers.append(f"Cc: {cc}")

        if headers:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(headers),
                attributes={"role": "email_headers"},
            ))

        model.add_element(Element(type=ElementType.HORIZONTAL_RULE, content=""))

        # Body
        body_text = self._extract_body(msg)
        if body_text:
            for para in body_text.split("\n\n"):
                para = para.strip()
                if para:
                    model.add_element(Element(
                        type=ElementType.PARAGRAPH,
                        content=para,
                    ))
        else:
            model.warnings.append("No readable text body found in email.")

        # ── Attachment conversion ──────────────────────────────────────────────
        self._process_attachments_eml(msg, model, depth, file_path)

    def _process_attachments_eml(
        self, msg, model: DocumentModel, depth: int, parent_path: Path
    ) -> None:
        """Process EML attachments: convert if handler available, list otherwise.

        Uses ErrorRateMonitor to abort if source becomes unreachable mid-processing.
        """
        converted_sections: list[str] = []
        unconverted_notes: list[str] = []
        attachment_metadata: list[dict] = []
        attachments_converted = 0
        error_monitor = ErrorRateMonitor(window_size=20, min_ops=5)

        for part in msg.walk():
            if error_monitor.should_abort():
                model.warnings.append("Attachment processing aborted: high error rate")
                log.error("eml_attachment_abort",
                          parent=parent_path.name,
                          errors=error_monitor.total_errors)
                break

            if part.get_content_maintype() == "multipart":
                continue

            filename = part.get_filename()
            if not filename:
                continue

            content = part.get_payload(decode=True)
            if content is None:
                attachment_metadata.append({"filename": filename, "status": "empty"})
                unconverted_notes.append(
                    f"- **{filename}** (empty attachment)"
                )
                continue

            md_content, meta = self._convert_attachment(
                filename=filename,
                content=content,
                depth=depth,
                parent_path=parent_path,
            )
            attachment_metadata.append(meta)

            if md_content:
                converted_sections.append(f"### Attachment: {filename}\n\n{md_content}")
                attachments_converted += 1
                error_monitor.record_success()
            else:
                size = len(content)
                status = meta.get("status", "unknown")
                note = f"- **{filename}** ({_human_size(size)})"
                if status == "no_handler":
                    note += " — no conversion handler available"
                elif status == "depth_limit":
                    note += " — nested email depth limit reached"
                elif status == "failed":
                    error = meta.get("error", "unknown error")
                    note += f" — conversion failed: {error}"
                    error_monitor.record_error(error)
                unconverted_notes.append(note)

        total_attachments = len(attachment_metadata)
        if total_attachments == 0:
            return

        # Store attachment stats in style_data for metadata
        model.style_data["attachment_count"] = total_attachments
        model.style_data["attachments_converted"] = attachments_converted
        model.style_data["email_attachments"] = [m.get("filename", "") for m in attachment_metadata]

        # Add Attachments section
        model.add_element(Element(type=ElementType.HORIZONTAL_RULE, content=""))
        model.add_element(Element(
            type=ElementType.HEADING, content="Attachments", level=2,
        ))

        for section in converted_sections:
            # Parse the section into heading + content
            lines = section.split("\n", 2)
            heading_text = lines[0].lstrip("# ").strip()
            body = lines[2] if len(lines) > 2 else ""
            model.add_element(Element(
                type=ElementType.HEADING, content=heading_text, level=3,
            ))
            if body.strip():
                model.add_element(Element(
                    type=ElementType.PARAGRAPH, content=body.strip(),
                ))

        if unconverted_notes:
            model.add_element(Element(
                type=ElementType.HEADING,
                content="Unconverted Attachments",
                level=3,
            ))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(unconverted_notes),
            ))

    def _convert_attachment(
        self,
        filename: str,
        content: bytes,
        depth: int,
        parent_path: Path,
    ) -> tuple[str, dict]:
        """
        Attempt to convert an email attachment using the format registry.

        Returns (markdown_content, metadata_dict). On failure, markdown_content
        is empty and metadata has error info.
        """
        ext = Path(filename).suffix.lower().lstrip(".")
        if not ext:
            return ("", {"filename": filename, "status": "no_handler", "size": len(content)})

        handler = get_handler(ext)
        if handler is None:
            return ("", {"filename": filename, "status": "no_handler", "size": len(content)})

        # Depth limit for nested emails
        if isinstance(handler, EmlHandler) and depth >= _MAX_ATTACHMENT_DEPTH:
            log.warning("eml_depth_limit", filename=filename, depth=depth,
                        msg=f"Skipping nested email at depth {depth} — recursion limit reached")
            return ("", {"filename": filename, "status": "depth_limit", "depth": depth})

        try:
            # Write to temp file so handler can read it
            suffix = f".{ext}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            try:
                if isinstance(handler, EmlHandler):
                    result_model = handler.ingest(tmp_path, depth=depth + 1)
                else:
                    result_model = handler.ingest(tmp_path)

                md_text = _model_to_markdown_body(result_model)
                return (md_text, {
                    "filename": filename,
                    "status": "converted",
                    "handler": type(handler).__name__,
                })
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        except Exception as exc:
            log.warning("attachment_conversion_failed",
                        filename=filename, parent=parent_path.name, error=str(exc))
            return ("", {
                "filename": filename,
                "status": "failed",
                "error": str(exc),
            })

    def _ingest_msg(self, file_path: Path, model: DocumentModel, depth: int = 0) -> None:
        """Best-effort parse of Outlook .msg file."""
        try:
            import olefile

            ole = olefile.OleFileIO(str(file_path))

            subject = self._msg_read_stream(ole, "__substg1.0_0037001F") or \
                      self._msg_read_stream(ole, "__substg1.0_0037001E") or ""
            from_addr = self._msg_read_stream(ole, "__substg1.0_0C1F001F") or \
                        self._msg_read_stream(ole, "__substg1.0_0C1F001E") or ""
            body = self._msg_read_stream(ole, "__substg1.0_1000001F") or \
                   self._msg_read_stream(ole, "__substg1.0_1000001E") or ""

            model.metadata.title = subject
            model.metadata.author = from_addr

            if subject:
                model.add_element(Element(type=ElementType.HEADING, content=subject, level=1))
            if from_addr:
                model.add_element(Element(
                    type=ElementType.PARAGRAPH,
                    content=f"From: {from_addr}",
                    attributes={"role": "email_headers"},
                ))

            model.add_element(Element(type=ElementType.HORIZONTAL_RULE, content=""))

            if body:
                for para in body.split("\n\n"):
                    para = para.strip()
                    if para:
                        model.add_element(Element(type=ElementType.PARAGRAPH, content=para))
            else:
                model.warnings.append("No readable text body found in .msg file.")

            # Process MSG attachments
            self._process_attachments_msg(ole, model, depth, file_path)

            ole.close()

        except ImportError:
            model.warnings.append("olefile not installed — .msg parsing unavailable.")
            # Fallback: try reading as binary text
            raw = file_path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
            # Extract any readable ASCII runs
            readable = re.findall(r"[\x20-\x7E]{20,}", text)
            for chunk in readable[:20]:
                model.add_element(Element(type=ElementType.PARAGRAPH, content=chunk))
        except Exception as exc:
            model.warnings.append(f"MSG parse error: {exc}")

    def _process_attachments_msg(
        self, ole, model: DocumentModel, depth: int, parent_path: Path
    ) -> None:
        """Process MSG attachments via olefile streams.

        Uses ErrorRateMonitor to abort if source becomes unreachable.
        """
        attachment_metadata: list[dict] = []
        converted_sections: list[str] = []
        unconverted_notes: list[str] = []
        attachments_converted = 0
        error_monitor = ErrorRateMonitor(window_size=20, min_ops=5)

        # MSG attachments are stored as __attach_version1.0_#XXXXXXXX substorages
        try:
            entries = ole.listdir()
        except Exception:
            return

        # Find attachment directories
        attach_dirs: set[str] = set()
        for entry in entries:
            if len(entry) >= 1 and entry[0].startswith("__attach"):
                attach_dirs.add(entry[0])

        for attach_dir in sorted(attach_dirs):
            if error_monitor.should_abort():
                model.warnings.append("MSG attachment processing aborted: high error rate")
                log.error("msg_attachment_abort",
                          parent=parent_path.name,
                          errors=error_monitor.total_errors)
                break

            # Read filename
            filename = None
            for stream_suffix in ("__substg1.0_3707001F", "__substg1.0_3707001E",
                                  "__substg1.0_3001001F", "__substg1.0_3001001E"):
                fn = self._msg_read_stream(ole, f"{attach_dir}/{stream_suffix}")
                if fn:
                    filename = fn
                    break

            if not filename:
                continue

            # Read content
            content = None
            content_stream = f"{attach_dir}/__substg1.0_37010102"
            try:
                if ole.exists(content_stream):
                    content = ole.openstream(content_stream).read()
            except Exception:
                pass

            if content is None:
                attachment_metadata.append({"filename": filename, "status": "empty"})
                unconverted_notes.append(f"- **{filename}** (empty attachment)")
                continue

            md_content, meta = self._convert_attachment(
                filename=filename,
                content=content,
                depth=depth,
                parent_path=parent_path,
            )
            attachment_metadata.append(meta)

            if md_content:
                converted_sections.append(f"### Attachment: {filename}\n\n{md_content}")
                attachments_converted += 1
                error_monitor.record_success()
            else:
                size = len(content)
                status = meta.get("status", "unknown")
                note = f"- **{filename}** ({_human_size(size)})"
                if status == "no_handler":
                    note += " — no conversion handler available"
                elif status == "depth_limit":
                    note += " — nested email depth limit reached"
                elif status == "failed":
                    error = meta.get("error", "unknown error")
                    note += f" — conversion failed: {error}"
                    error_monitor.record_error(error)
                unconverted_notes.append(note)

        total_attachments = len(attachment_metadata)
        if total_attachments == 0:
            return

        model.style_data["attachment_count"] = total_attachments
        model.style_data["attachments_converted"] = attachments_converted
        model.style_data["email_attachments"] = [m.get("filename", "") for m in attachment_metadata]

        model.add_element(Element(type=ElementType.HORIZONTAL_RULE, content=""))
        model.add_element(Element(
            type=ElementType.HEADING, content="Attachments", level=2,
        ))

        for section in converted_sections:
            lines = section.split("\n", 2)
            heading_text = lines[0].lstrip("# ").strip()
            body = lines[2] if len(lines) > 2 else ""
            model.add_element(Element(
                type=ElementType.HEADING, content=heading_text, level=3,
            ))
            if body.strip():
                model.add_element(Element(
                    type=ElementType.PARAGRAPH, content=body.strip(),
                ))

        if unconverted_notes:
            model.add_element(Element(
                type=ElementType.HEADING,
                content="Unconverted Attachments",
                level=3,
            ))
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="\n".join(unconverted_notes),
            ))

    @staticmethod
    def _msg_read_stream(ole, stream_name: str) -> str | None:
        try:
            if ole.exists(stream_name):
                data = ole.openstream(stream_name).read()
                if stream_name.endswith("001F"):
                    return data.decode("utf-16-le", errors="replace").rstrip("\x00")
                else:
                    return data.decode("utf-8", errors="replace").rstrip("\x00")
        except Exception:
            pass
        return None

    def _extract_body(self, msg) -> str:
        """Extract plain-text body from email, preferring text/plain."""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    payload = part.get_content()
                    if isinstance(payload, str):
                        return payload
            # Fallback: try text/html stripped
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    payload = part.get_content()
                    if isinstance(payload, str):
                        return self._strip_html(payload)
        else:
            payload = msg.get_content()
            if isinstance(payload, str):
                return payload
        return ""

    @staticmethod
    def _strip_html(html: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"</(p|div|tr|li)>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    @staticmethod
    def _list_attachments(msg) -> list[str]:
        names: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                fn = part.get_filename()
                if fn:
                    names.append(fn)
        return names

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        t_start = time.perf_counter()
        log.info("handler_export_start", filename=output_path.name, target_format="eml", tier=1)

        from email.mime.text import MIMEText

        # Build body text
        body_parts: list[str] = []
        for elem in model.elements:
            if elem.type in (ElementType.HEADING, ElementType.PARAGRAPH):
                text = self._strip_md(elem.content)
                if elem.attributes.get("role") != "email_headers":
                    body_parts.append(text)
            elif elem.type == ElementType.HORIZONTAL_RULE:
                body_parts.append("-" * 40)

        body = "\n\n".join(body_parts)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = model.metadata.title or ""
        msg["From"] = model.metadata.author or "unknown@markflow.local"
        msg["To"] = ""

        output_path.write_text(msg.as_string(), encoding="utf-8")

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_export_complete", filename=output_path.name, duration_ms=duration_ms)

    @staticmethod
    def _strip_md(text: str) -> str:
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ── Style extraction ──────────────────────────────────────────────────────

    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        return {
            "document_level": {
                "extension": file_path.suffix.lower(),
                "font_family": "monospace",
                "font_name": "Courier New",
            }
        }
