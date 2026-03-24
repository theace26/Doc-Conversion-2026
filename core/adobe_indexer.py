"""
Adobe file indexer — Level 2 indexing for creative file formats.

Extracts metadata (XMP/EXIF via exiftool) and text layers where possible:
  .ai    — embedded PDF stream text via pdfplumber
  .psd   — text layers via psd-tools
  .indd, .aep, .prproj, .xd — metadata only
"""

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from core.database import upsert_adobe_index

log = structlog.get_logger(__name__)

MAX_TEXT_BYTES = 500 * 1024  # 500 KB max total text per file


@dataclass
class AdobeIndexResult:
    source_path: Path
    file_ext: str
    file_size_bytes: int
    metadata: dict = field(default_factory=dict)
    text_layers: list[str] = field(default_factory=list)
    indexing_level: int = 2
    success: bool = True
    error_msg: str | None = None
    duration_ms: int = 0


class AdobeIndexer:
    """Indexes Adobe creative files at Level 2: metadata + text layer extraction."""

    def __init__(self, db_path: str = ""):
        pass

    async def index_file(self, source_path: Path) -> AdobeIndexResult:
        """Dispatch by extension, upsert result into DB."""
        t_start = time.perf_counter()
        source_path = Path(source_path)
        ext = source_path.suffix.lower()

        try:
            file_size = source_path.stat().st_size
        except OSError as exc:
            return AdobeIndexResult(
                source_path=source_path,
                file_ext=ext,
                file_size_bytes=0,
                success=False,
                error_msg=f"Cannot stat file: {exc}",
            )

        try:
            if ext == ".ai":
                metadata, text_layers = await self._index_ai(source_path)
            elif ext == ".psd":
                metadata, text_layers = await self._index_psd(source_path)
            elif ext in (".indd", ".aep", ".prproj", ".xd"):
                metadata, text_layers = await self._index_metadata_only(source_path)
            else:
                return AdobeIndexResult(
                    source_path=source_path,
                    file_ext=ext,
                    file_size_bytes=file_size,
                    success=False,
                    error_msg=f"Unsupported Adobe extension: {ext}",
                )

            # Truncate text layers if total > MAX_TEXT_BYTES
            text_layers = self._truncate_text(text_layers)

            # Upsert into DB
            await upsert_adobe_index(
                source_path=str(source_path),
                file_ext=ext,
                file_size_bytes=file_size,
                metadata=metadata,
                text_layers=text_layers,
            )

            duration_ms = int((time.perf_counter() - t_start) * 1000)
            return AdobeIndexResult(
                source_path=source_path,
                file_ext=ext,
                file_size_bytes=file_size,
                metadata=metadata,
                text_layers=text_layers,
                success=True,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            duration_ms = int((time.perf_counter() - t_start) * 1000)
            log.error(
                "adobe_index_error",
                path=str(source_path),
                ext=ext,
                error=str(exc),
            )
            return AdobeIndexResult(
                source_path=source_path,
                file_ext=ext,
                file_size_bytes=file_size,
                success=False,
                error_msg=str(exc),
                duration_ms=duration_ms,
            )

    async def _extract_metadata(self, path: Path) -> dict:
        """Run exiftool on path. Returns dict of XMP/EXIF fields."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["exiftool", "-json", "-n", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                log.warning("exiftool_error", path=str(path), stderr=result.stderr[:200])
                return {}

            data_list = json.loads(result.stdout)
            if not data_list:
                return {}

            metadata = data_list[0]

            # Strip binary/null values and truncate long strings
            cleaned = {}
            for k, v in metadata.items():
                if v is None:
                    continue
                if isinstance(v, (bytes, bytearray)):
                    continue
                if isinstance(v, str) and len(v) > 2000:
                    v = v[:2000]
                cleaned[k] = v

            return cleaned

        except FileNotFoundError:
            log.warning("exiftool_not_found")
            return {"_error": "exiftool not installed"}
        except subprocess.TimeoutExpired:
            log.warning("exiftool_timeout", path=str(path))
            return {"_error": "exiftool timeout"}
        except Exception as exc:
            log.warning("exiftool_exception", path=str(path), error=str(exc))
            return {"_error": str(exc)}

    async def _index_ai(self, path: Path) -> tuple[dict, list[str]]:
        """
        .ai files contain an embedded PDF stream.
        Use pdfplumber to extract text.
        """
        metadata = await self._extract_metadata(path)
        text_layers: list[str] = []

        try:
            import pdfplumber
            pdf = await asyncio.to_thread(pdfplumber.open, str(path))
            try:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    if text.strip():
                        text_layers.append(text)
            finally:
                pdf.close()
        except Exception as exc:
            log.warning("ai_pdf_extract_fail", path=str(path), error=str(exc))
            # Return metadata only — don't fail the whole indexing

        return metadata, text_layers

    async def _index_psd(self, path: Path) -> tuple[dict, list[str]]:
        """Use psd-tools to extract text layers from PSD files."""
        metadata = await self._extract_metadata(path)
        text_layers: list[str] = []

        try:
            from psd_tools import PSDImage
            psd = await asyncio.to_thread(PSDImage.open, str(path))

            def _extract_text_layers(layers):
                texts = []
                for layer in layers:
                    # Check for type/text layers
                    if hasattr(layer, "kind") and layer.kind == "type":
                        try:
                            if hasattr(layer, "text") and layer.text:
                                texts.append(layer.text)
                        except Exception:
                            pass
                    # Recurse into groups
                    if hasattr(layer, "__iter__"):
                        try:
                            texts.extend(_extract_text_layers(layer))
                        except Exception:
                            pass
                return texts

            text_layers = await asyncio.to_thread(_extract_text_layers, psd)

        except Exception as exc:
            log.warning("psd_extract_fail", path=str(path), error=str(exc))

        return metadata, text_layers

    async def _index_metadata_only(self, path: Path) -> tuple[dict, list[str]]:
        """.indd, .aep, .prproj, .xd — metadata only."""
        metadata = await self._extract_metadata(path)
        return metadata, []

    @staticmethod
    def _truncate_text(text_layers: list[str]) -> list[str]:
        """Truncate total text to MAX_TEXT_BYTES by dropping last layers first."""
        total = sum(len(t.encode("utf-8", errors="replace")) for t in text_layers)
        if total <= MAX_TEXT_BYTES:
            return text_layers

        result = []
        running = 0
        for text in text_layers:
            size = len(text.encode("utf-8", errors="replace"))
            if running + size > MAX_TEXT_BYTES:
                break
            result.append(text)
            running += size

        return result
