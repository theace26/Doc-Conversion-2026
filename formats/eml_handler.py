"""
Email format handler — EML and MSG files.

Ingest:
  EML: Uses stdlib email module to parse headers and body.
  MSG: Uses compressed_rtf via olefile for Outlook .msg files.
  Extracts subject as heading, headers as metadata, body as paragraphs.

Export:
  Generates RFC 5322 compliant .eml from DocumentModel.
"""

import email
import email.policy
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


@register_handler
class EmlHandler(FormatHandler):
    """Email handler for .eml and .msg files."""

    EXTENSIONS = ["eml", "msg"]

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, file_path: Path) -> DocumentModel:
        t_start = time.perf_counter()
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        log.info("handler_ingest_start", filename=file_path.name, format=ext.lstrip("."))

        model = DocumentModel()
        model.metadata = DocumentMetadata(
            source_file=file_path.name,
            source_format=ext.lstrip("."),
        )

        if ext == ".msg":
            self._ingest_msg(file_path, model)
        else:
            self._ingest_eml(file_path, model)

        model.metadata.page_count = 1

        duration_ms = int((time.perf_counter() - t_start) * 1000)
        log.info("handler_ingest_complete", filename=file_path.name,
                 element_count=len(model.elements), duration_ms=duration_ms)
        return model

    def _ingest_eml(self, file_path: Path, model: DocumentModel) -> None:
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

        # Attachment list
        attachments = self._list_attachments(msg)
        if attachments:
            model.add_element(Element(
                type=ElementType.PARAGRAPH,
                content="Attachments: " + ", ".join(attachments),
                attributes={"role": "attachment_list"},
            ))
            model.style_data["email_attachments"] = attachments

    def _ingest_msg(self, file_path: Path, model: DocumentModel) -> None:
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

            ole.close()

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
