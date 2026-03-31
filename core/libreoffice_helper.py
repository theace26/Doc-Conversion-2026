"""
Shared LibreOffice headless conversion helper.

Used by DocxHandler (.doc → .docx), XlsxHandler (.xls → .xlsx),
and PptxHandler (.ppt → .pptx) to preprocess legacy Office formats
before ingesting with library-level parsers.
"""

import shutil
import tempfile
from pathlib import Path
import subprocess

import structlog

log = structlog.get_logger(__name__)


def convert_with_libreoffice(
    source_path: Path,
    target_format: str,
    timeout: int = 120,
) -> Path:
    """
    Convert a file to *target_format* using LibreOffice headless.

    Returns a Path to the converted file (caller must delete when done).
    Raises RuntimeError if LibreOffice is not available or conversion fails.

    Parameters
    ----------
    source_path : Path
        Input file (.doc, .xls, .ppt, etc.)
    target_format : str
        LibreOffice output format string, e.g. "docx", "xlsx", "pptx".
    timeout : int
        Subprocess timeout in seconds. Default 120 (legacy files can be slow).
    """
    for binary in ("libreoffice", "soffice"):
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    [
                        binary,
                        "--headless",
                        "--convert-to",
                        target_format,
                        "--outdir",
                        tmpdir,
                        str(source_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                if result.returncode == 0:
                    out_path = Path(tmpdir) / (
                        source_path.stem + "." + target_format
                    )
                    if out_path.exists():
                        stable = Path(
                            tempfile.mktemp(suffix="." + target_format)
                        )
                        shutil.copy2(out_path, stable)
                        log.info(
                            "libreoffice_convert_ok",
                            source=source_path.name,
                            target_format=target_format,
                        )
                        return stable
                else:
                    log.warning(
                        "libreoffice_convert_nonzero",
                        source=source_path.name,
                        returncode=result.returncode,
                        stderr=result.stderr[:500] if result.stderr else "",
                    )
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"LibreOffice timed out after {timeout}s converting "
                f"{source_path.name} to {target_format}"
            )

    raise RuntimeError(
        f"Cannot convert {source_path.name}: LibreOffice not found. "
        "Install libreoffice-headless."
    )
