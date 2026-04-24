"""Pre-flight validation for images headed to a vision API (v0.29.9).

Philosophy: API calls are money. Catch the three classes of input that
reliably produce 400s *before* we encode to base64 and POST — corrupt
bytes, wrong-format bytes, and wildly out-of-range dimensions. These
three filters together eliminate most of the avoidable-400 traffic we
were paying for.

Returns a structured `PreflightResult` rather than raising, so the
caller can build up a list of (row, reason) failures and report them
through the existing write_batch_results path without the batch
falling over on one bad file.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


# Dimension range that Anthropic's vision pipeline handles cleanly.
# Below 100px per edge the model receives too little signal to analyze
# meaningfully; above ~8000px Anthropic has been observed to 400 with
# "image too large" even when under the 5 MB byte cap. These limits are
# conservative and err toward "send it" — they only reject the
# pathological cases.
_MIN_EDGE_PX = 100
_MAX_EDGE_PX = 8000

# Anthropic vision MIME allow-list. Duplicated from vision_adapter to
# avoid a circular import; kept in sync by comment convention.
_VISION_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    error: str | None = None           # user-visible error string for analysis_queue.error
    width: int | None = None
    height: int | None = None
    detected_mime: str | None = None


def validate_image_for_vision(
    raw: bytes,
    filename: str | None = None,
    detected_mime: str | None = None,
) -> PreflightResult:
    """Run three cheap checks that mirror Anthropic's 400-triggering
    input classes. The caller is expected to have already done MIME
    detection via `detect_mime(path)` and passed the result in — this
    function does NOT re-read the file.

    Order of checks:
      1. MIME in allow-list (cheapest: string compare on a small set)
      2. PIL can open + verify the bytes (catches corruption, truncation)
      3. Dimensions within sane bounds (catches edge-case reject patterns)

    Any failure short-circuits the rest. Success returns the verified
    width/height so callers can log them without re-opening.
    """
    if not raw:
        return PreflightResult(ok=False, error="[preflight] empty image bytes")

    if detected_mime and detected_mime not in _VISION_ALLOWED_MIMES:
        return PreflightResult(
            ok=False,
            error=f"[preflight] unsupported mime {detected_mime} (vision accepts jpeg/png/gif/webp)",
            detected_mime=detected_mime,
        )

    # PIL.verify() is header-only and fast — it catches truncated or
    # corrupt headers without decoding pixel data. We pair it with a
    # second Image.open + load() in case the header is fine but the
    # IDAT/strip data is broken (rare but has been seen on files
    # truncated mid-upload).
    try:
        # Lazy import: keeps module load cheap for callers that never
        # need vision, and avoids pulling in PIL's C extensions on
        # Python startup.
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover — PIL is required
        return PreflightResult(ok=False, error=f"[preflight] PIL unavailable: {exc}")

    # --- Header verify (fast failure on garbage) ---
    try:
        with Image.open(BytesIO(raw)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.info(
            "vision_preflight.pil_verify_failed",
            filename=filename,
            error=f"{type(exc).__name__}: {exc}",
        )
        return PreflightResult(
            ok=False,
            error=f"[preflight] PIL can't decode bytes: {type(exc).__name__}: {exc}",
            detected_mime=detected_mime,
        )

    # --- Dimension check (verify consumed the stream; reopen) ---
    try:
        with Image.open(BytesIO(raw)) as img:
            width, height = img.size
    except Exception as exc:
        log.info(
            "vision_preflight.pil_size_failed",
            filename=filename,
            error=f"{type(exc).__name__}: {exc}",
        )
        return PreflightResult(
            ok=False,
            error=f"[preflight] couldn't read image dimensions: {exc}",
            detected_mime=detected_mime,
        )

    if min(width, height) < _MIN_EDGE_PX:
        return PreflightResult(
            ok=False,
            error=f"[preflight] image too small ({width}x{height}px; "
                  f"min edge {_MIN_EDGE_PX}px for vision analysis)",
            width=width, height=height, detected_mime=detected_mime,
        )
    if max(width, height) > _MAX_EDGE_PX:
        return PreflightResult(
            ok=False,
            error=f"[preflight] image too large ({width}x{height}px; "
                  f"max edge {_MAX_EDGE_PX}px — resize or split before analysis)",
            width=width, height=height, detected_mime=detected_mime,
        )

    return PreflightResult(
        ok=True,
        width=width, height=height, detected_mime=detected_mime,
    )
