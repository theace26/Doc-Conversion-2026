"""Rasterize vector/layered source files to PNG for vision analysis.

Anthropic/OpenAI/Gemini vision APIs only accept raster formats (JPEG/PNG/GIF/WEBP).
EPS/AI/PS files need Ghostscript to render; PSD files need PIL composite extraction.

Cached output keys off the content_hash so retries reuse the render.
"""

import asyncio
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

VECTOR_EXTENSIONS = {".eps", ".ai", ".ps"}
LAYERED_EXTENSIONS = {".psd", ".psb"}
SUPPORTED_EXTENSIONS = VECTOR_EXTENSIONS | LAYERED_EXTENSIONS

DEFAULT_CACHE_DIR = Path("/app/data/vector_cache")
DEFAULT_DPI = 150
_GS_TIMEOUT_SECONDS = 120


class RasterizationError(Exception):
    """Raised when a source file cannot be rasterized."""


def is_rasterizable(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def cache_path_for(content_hash: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / f"{content_hash}.png"


async def rasterize(
    source: Path,
    content_hash: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    dpi: int = DEFAULT_DPI,
) -> Path:
    """Return a PNG render of source, caching by content_hash.

    Cache hit: no work, returns cached path.
    Cache miss: runs Ghostscript (EPS/AI/PS) or PIL (PSD/PSB), writes to cache.
    """
    out = cache_path_for(content_hash, cache_dir)
    if out.exists() and out.stat().st_size > 0:
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    ext = source.suffix.lower()

    if ext in VECTOR_EXTENSIONS:
        await _run_ghostscript(source, out, dpi)
    elif ext in LAYERED_EXTENSIONS:
        await asyncio.to_thread(_pil_psd_composite, source, out)
    else:
        raise RasterizationError(f"unsupported extension: {ext}")

    if not out.exists() or out.stat().st_size == 0:
        raise RasterizationError(f"rasterization produced empty output: {out}")

    log.info(
        "vector_rasterizer.rendered",
        source=str(source),
        output=str(out),
        bytes=out.stat().st_size,
    )
    return out


async def _run_ghostscript(source: Path, output: Path, dpi: int) -> None:
    cmd = [
        "gs", "-dNOPAUSE", "-dBATCH", "-dQUIET", "-dSAFER",
        "-sDEVICE=png16m", f"-r{dpi}",
        "-dFirstPage=1", "-dLastPage=1",
        f"-sOutputFile={output}", str(source),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GS_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RasterizationError(f"ghostscript timed out on {source}")
    if proc.returncode != 0:
        tail = (stderr or b"").decode(errors="replace")[-400:]
        raise RasterizationError(f"ghostscript rc={proc.returncode}: {tail}")


def _pil_psd_composite(source: Path, output: Path) -> None:
    from PIL import Image
    with Image.open(source) as img:
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(output, format="PNG", optimize=True)


def _content_hash_fallback(source: Path) -> str:
    """Stable cache key when content_hash is unavailable."""
    import hashlib
    return "path_" + hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:32]
