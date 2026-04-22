"""
Shared LibreOffice headless conversion helper.

Used by DocxHandler (.doc → .docx), XlsxHandler (.xls → .xlsx),
and PptxHandler (.ppt → .pptx) to preprocess legacy Office formats
before ingesting with library-level parsers.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

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
    binary_found = False
    last_error: str | None = None
    last_returncode: int | None = None

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
                # Reaching here means the binary was found and ran.
                binary_found = True
                if result.returncode == 0:
                    out_path = Path(tmpdir) / (
                        source_path.stem + "." + target_format
                    )
                    if out_path.exists():
                        # v0.29.0 SEC-H18: mktemp() returns a name without
                        # creating the file, which leaves a TOCTOU window.
                        # mkstemp() atomically creates (and O_EXCL-locks) the
                        # file; shutil.copy2 then overwrites it in place.
                        _fd, _stable_name = tempfile.mkstemp(suffix="." + target_format)
                        os.close(_fd)
                        stable = Path(_stable_name)
                        shutil.copy2(out_path, stable)
                        log.info(
                            "libreoffice_convert_ok",
                            source=source_path.name,
                            target_format=target_format,
                        )
                        return stable
                    # rc=0 but no output file (rare; corrupt input that
                    # LibreOffice "successfully" silently dropped)
                    last_error = "exited 0 but produced no output file"
                    last_returncode = 0
                    log.warning(
                        "libreoffice_convert_no_output",
                        source=source_path.name,
                        target_format=target_format,
                    )
                else:
                    last_returncode = result.returncode
                    last_error = (
                        result.stderr.strip()[:500] if result.stderr else "no stderr"
                    )
                    log.warning(
                        "libreoffice_convert_nonzero",
                        source=source_path.name,
                        binary=binary,
                        returncode=result.returncode,
                        stderr=last_error,
                    )
                    # Try the other binary name in case `libreoffice` is a
                    # broken symlink but `soffice` works.
                    continue
        except FileNotFoundError:
            # Binary genuinely not on PATH; try the next name.
            continue
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"LibreOffice timed out after {timeout}s converting "
                f"{source_path.name} to {target_format}"
            )

    if not binary_found:
        raise RuntimeError(
            f"Cannot convert {source_path.name}: LibreOffice not found on PATH. "
            "Install libreoffice (libreoffice-writer/-impress for Office formats)."
        )
    raise RuntimeError(
        f"LibreOffice failed to convert {source_path.name} to {target_format} "
        f"(exit={last_returncode}): {last_error or 'unknown error'}"
    )
