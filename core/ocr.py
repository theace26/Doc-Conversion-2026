"""
OCR pipeline — multi-signal detection, image preprocessing, and Tesseract extraction.

OCRDetector: multi-signal heuristic to determine if a PDF page needs OCR
  (entropy, edge density, structured horizontal lines).

OCRProcessor: preprocess (deskew, threshold, denoise, scale) + Tesseract
  (--oem 3 --psm 6) + per-word confidence scoring with flag generation for review.

OCRFlagStore: in-memory + SQLite storage for pending review flags per batch.
"""

import math
import os
import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage
    import numpy as np

log = structlog.get_logger(__name__)

DEBUG = os.getenv("DEBUG", "false").lower() == "true"


# ── Detection ─────────────────────────────────────────────────────────────────

def needs_ocr(image: "PILImage") -> bool:
    """
    Multi-signal heuristic — returns True if image likely contains extractable text.

    Signals (applied in order):
    1. Entropy  — very low stddev = blank/solid → skip
    2. Edge density — very low edge mean = featureless → skip
    3. Entropy + edges combo — very high entropy AND very low edge structure
       = natural photo with no text lines → skip
    4. Default — assume OCR is useful
    """
    from PIL import ImageFilter, ImageStat

    gray = image.convert("L")

    # Signal 1: blank / near-blank page
    stat = ImageStat.Stat(gray)
    stddev = stat.stddev[0]
    if stddev < 8.0:
        log.debug("ocr_detection", signal="blank_page", needs_ocr=False, stddev=stddev)
        return False

    # Signal 2: edge density
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_mean = edge_stat.mean[0] / 255.0
    if edge_mean < 0.005:
        log.debug("ocr_detection", signal="no_edges", needs_ocr=False, edge_mean=edge_mean)
        return False

    # Signal 3: high-entropy + very low structured-edge → natural photo
    hist = gray.histogram()
    total_px = sum(hist)
    entropy = 0.0
    for count in hist:
        if count > 0:
            p = count / total_px
            entropy -= p * math.log2(p)

    if entropy > 7.5 and edge_mean < 0.04:
        log.debug(
            "ocr_detection",
            signal="photo_heuristic",
            needs_ocr=False,
            entropy=round(entropy, 2),
            edge_mean=round(edge_mean, 4),
        )
        return False

    log.debug(
        "ocr_detection",
        signal="text_density",
        needs_ocr=True,
        stddev=round(stddev, 1),
        edge_mean=round(edge_mean, 4),
        entropy=round(entropy, 2),
    )
    return True


# ── Preprocessing ─────────────────────────────────────────────────────────────

def preprocess_image(image: "PILImage") -> "PILImage":
    """
    Prepare a page image for Tesseract:
      grayscale → deskew → denoise (MedianFilter) → Otsu threshold → scale.

    Returns an L-mode (grayscale) image ready for pytesseract.
    """
    from PIL import ImageFilter

    # 1. Grayscale
    gray = image.convert("L")

    # 2. Deskew
    angle = _detect_skew(gray)
    if 0.5 < abs(angle) < 15.0:
        log.debug("ocr.preprocess", step="deskew", angle=round(angle, 2))
        gray = gray.rotate(-angle, expand=True, fillcolor=255)

    # 3. Denoise — gentle 3×3 median filter
    gray = gray.filter(ImageFilter.MedianFilter(3))

    # 4. Binarise via Otsu threshold
    gray = _otsu_threshold(gray)

    # 5. Scale — upscale if image is too small for Tesseract (< 1700 px wide)
    w, h = gray.size
    if w < 1700:
        scale = max(1700 / w, 1.5)
        new_w = int(w * scale)
        new_h = int(h * scale)
        from PIL import Image
        gray = gray.resize((new_w, new_h), Image.LANCZOS)
        log.debug(
            "ocr.preprocess", step="scale", scale=round(scale, 2), new_size=(new_w, new_h)
        )

    return gray


def _detect_skew(gray: "PILImage") -> float:
    """
    Estimate document skew via projection profile variance.

    Coarse search at 1° steps, then fine-tuned at 0.25° around the best candidate.
    Returns the detected skew angle in degrees (positive = clockwise rotation present).
    """
    try:
        import numpy as np
    except ImportError:
        return 0.0

    arr = np.array(gray)
    binary = (arr < 128).astype(np.uint8)

    best_angle = 0.0
    best_score = -1.0

    # Coarse pass: −15° to +15° in 1° steps
    for deg in range(-15, 16):
        score = _projection_score(binary, float(deg))
        if score > best_score:
            best_score = score
            best_angle = float(deg)

    # Fine pass: ±1° around best in 0.25° steps
    fine_start = int((best_angle - 1.0) * 4)
    fine_end = int((best_angle + 1.0) * 4) + 1
    for quarter in range(fine_start, fine_end):
        angle = quarter / 4.0
        score = _projection_score(binary, angle)
        if score > best_score:
            best_score = score
            best_angle = angle

    return best_angle


def _projection_score(binary: "np.ndarray", angle: float) -> float:
    """Rotate binary image and return row-sum variance (higher = better alignment)."""
    from PIL import Image
    import numpy as np

    img = Image.fromarray((binary * 255).astype("uint8"))
    rotated = img.rotate(angle, expand=True, fillcolor=0)
    arr = np.array(rotated) > 128
    row_sums = arr.sum(axis=1).astype(float)
    return float(row_sums.var())


def _otsu_threshold(gray: "PILImage") -> "PILImage":
    """Binarise a grayscale image using Otsu's method."""
    try:
        import numpy as np
        from PIL import Image

        arr = np.array(gray)
        hist, _ = np.histogram(arr.flatten(), bins=256, range=(0, 256))
        total = arr.size
        sum_total = float(np.dot(np.arange(256, dtype=float), hist))
        sum_b = 0.0
        w_b = 0
        max_var = 0.0
        threshold = 128

        for t in range(256):
            w_b += int(hist[t])
            if w_b == 0:
                continue
            w_f = total - w_b
            if w_f == 0:
                break
            sum_b += t * float(hist[t])
            mean_b = sum_b / w_b
            mean_f = (sum_total - sum_b) / w_f
            var_between = w_b * w_f * (mean_b - mean_f) ** 2
            if var_between > max_var:
                max_var = var_between
                threshold = t

        binary = (arr > threshold).astype(np.uint8) * 255
        return Image.fromarray(binary, mode="L")

    except ImportError:
        # Fallback: fixed midpoint threshold
        return gray.point(lambda p: 255 if p > 128 else 0)


# ── OCR Execution ─────────────────────────────────────────────────────────────

def ocr_page(
    image: "PILImage",
    config: "OCRConfig",
    page_num: int,
    batch_id: str,
    file_name: str,
) -> "OCRPage":
    """
    Run Tesseract on one page image and return an OCRPage.

    Preprocessing is applied when config.preprocess is True.
    Debug artifacts are saved when the DEBUG env var is set.
    """
    import time as _time

    import pytesseract
    from pytesseract import Output

    from core.ocr_models import OCRConfig, OCRPage, OCRWord

    t_start = _time.perf_counter()
    w, h = image.size
    log.info("ocr_page_start", filename=file_name, page_num=page_num, image_size_px=f"{w}x{h}")

    # ── Preprocess ────────────────────────────────────────────────────────────
    processed = preprocess_image(image) if config.preprocess else image.convert("L")

    # ── Debug artifacts ───────────────────────────────────────────────────────
    if DEBUG:
        debug_dir = Path("output") / batch_id / "_ocr_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(file_name).stem
        image.save(debug_dir / f"{stem}_page{page_num}_original.png")
        processed.save(debug_dir / f"{stem}_page{page_num}_preprocessed.png")

    # ── Tesseract ─────────────────────────────────────────────────────────────
    tess_config = f"--oem {config.oem} --psm {config.psm} -l {config.language}"
    data = pytesseract.image_to_data(processed, config=tess_config, output_type=Output.DICT)

    # ── Parse word-level output ───────────────────────────────────────────────
    words: list[OCRWord] = []
    n = len(data["text"])

    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        conf = float(data["conf"][i])
        if conf < 0:
            conf = 0.0
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        words.append(
            OCRWord(
                text=text,
                confidence=conf,
                bbox=(x, y, x + w, y + h),
                line_num=data["line_num"][i],
                word_num=data["word_num"][i],
            )
        )

    full_text = _build_full_text(data)

    valid_confs = [w.confidence for w in words if w.confidence >= 0]
    avg_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 0.0

    page = OCRPage(
        page_num=page_num,
        words=words,
        full_text=full_text,
        average_confidence=avg_conf,
    )

    duration_ms = int((_time.perf_counter() - t_start) * 1000)
    log.info(
        "ocr_page_complete",
        filename=file_name,
        page_num=page_num,
        word_count=len(words),
        mean_confidence=round(avg_conf, 1),
        duration_ms=duration_ms,
    )
    return page


def _build_full_text(data: dict) -> str:
    """Reconstruct readable text from a Tesseract output dict."""
    lines: dict[tuple[int, int], list[str]] = {}
    n = len(data["text"])

    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        key = (data["block_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(text)

    return "\n".join(" ".join(words) for words in lines.values())


# ── Confidence Flagging ───────────────────────────────────────────────────────

def flag_low_confidence(
    page: "OCRPage",
    config: "OCRConfig",
    batch_id: str,
    file_name: str,
    page_image: "PILImage | None" = None,
) -> "list[OCRFlag]":
    """
    Group consecutive low-confidence words on the same line into OCRFlags.

    Each flag gets a cropped image saved to output/<batch_id>/_ocr_debug/.
    """
    from core.ocr_models import OCRFlag

    flags: list[OCRFlag] = []
    threshold = config.confidence_threshold

    # Index words by line
    lines: dict[int, list] = {}
    for word in page.words:
        lines.setdefault(word.line_num, []).append(word)

    for _line_num, line_words in sorted(lines.items()):
        group: list = []
        for word in line_words:
            if word.confidence < threshold:
                group.append(word)
            else:
                if group:
                    flags.append(
                        _make_flag(group, batch_id, file_name, page.page_num, page_image)
                    )
                    group = []
        if group:
            flags.append(
                _make_flag(group, batch_id, file_name, page.page_num, page_image)
            )

    if flags:
        min_conf = min(f.confidence for f in flags) if flags else 0.0
        log.info(
            "ocr_low_confidence",
            filename=file_name,
            page_num=page.page_num,
            flag_count=len(flags),
            min_confidence=round(min_conf, 1),
        )
    return flags


def _make_flag(
    group: list,
    batch_id: str,
    file_name: str,
    page_num: int,
    page_image: "PILImage | None",
) -> "OCRFlag":
    """Build an OCRFlag for a group of adjacent low-confidence words."""
    from core.ocr_models import OCRFlag, OCRFlagStatus

    flag_id = str(_uuid.uuid4())

    x1 = min(w.bbox[0] for w in group)
    y1 = min(w.bbox[1] for w in group)
    x2 = max(w.bbox[2] for w in group)
    y2 = max(w.bbox[3] for w in group)

    text = " ".join(w.text for w in group)
    avg_conf = sum(w.confidence for w in group) / len(group)

    image_path: str | None = None
    if page_image is not None:
        pad = 10
        crop_box = (
            max(0, x1 - pad),
            max(0, y1 - pad),
            min(page_image.width, x2 + pad),
            min(page_image.height, y2 + pad),
        )
        # Only crop if box has positive area
        if crop_box[2] > crop_box[0] and crop_box[3] > crop_box[1]:
            cropped = page_image.crop(crop_box)
            debug_dir = Path("output") / batch_id / "_ocr_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(file_name).stem
            img_filename = f"{stem}_flag_{flag_id}.png"
            img_path = debug_dir / img_filename
            cropped.save(img_path)
            image_path = str(img_path).replace("\\", "/")

    return OCRFlag(
        flag_id=flag_id,
        batch_id=batch_id,
        file_name=file_name,
        page_num=page_num,
        region_bbox=(x1, y1, x2, y2),
        ocr_text=text,
        confidence=avg_conf,
        image_path=image_path,
        status=OCRFlagStatus.PENDING,
    )


# ── Top-Level Async Entry Point ───────────────────────────────────────────────

async def run_ocr(
    images: "list[tuple[int, PILImage]]",
    config: "OCRConfig",
    batch_id: str,
    file_name: str,
) -> "OCRResult":
    """
    OCR a list of (page_num, PIL.Image) tuples asynchronously.

    - Each page is processed in asyncio.to_thread() (Tesseract is CPU-bound).
    - Flags are persisted to SQLite.
    - In unattended mode all flags are auto-accepted and a warning is logged.
    - Returns OCRResult with all pages and flags.
    """
    import asyncio

    from core.database import insert_ocr_flag
    from core.ocr_models import OCRFlagStatus, OCRResult

    all_pages = []
    all_flags = []

    for page_num, image in images:
        page = await asyncio.to_thread(
            ocr_page, image, config, page_num, batch_id, file_name
        )
        page_flags = await asyncio.to_thread(
            flag_low_confidence, page, config, batch_id, file_name, image
        )

        if config.unattended:
            for flag in page_flags:
                flag.status = OCRFlagStatus.ACCEPTED

        page.flags = page_flags
        all_pages.append(page)
        all_flags.extend(page_flags)

    # Persist to DB
    for flag in all_flags:
        await insert_ocr_flag(flag)

    if config.unattended and all_flags:
        log.warning(
            "ocr.unattended_auto_accept",
            batch_id=batch_id,
            file_name=file_name,
            count=len(all_flags),
        )

    total_words = sum(len(p.words) for p in all_pages)
    flagged_words = sum(
        sum(1 for w in p.words if w.confidence < config.confidence_threshold)
        for p in all_pages
    )
    valid_confs = [
        w.confidence for p in all_pages for w in p.words if w.confidence >= 0
    ]
    avg_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 0.0

    log.info(
        "ocr_complete",
        filename=file_name,
        page_count=len(all_pages),
        flagged_count=len(all_flags),
        overall_confidence=round(avg_conf, 1),
    )

    return OCRResult(
        pages=all_pages,
        total_words=total_words,
        flagged_words=flagged_words,
        average_confidence=avg_conf,
        flags=all_flags,
    )


# ── Type aliases for re-export ─────────────────────────────────────────────────
# (avoids importing from ocr_models in callers that already import ocr)
from core.ocr_models import (  # noqa: E402
    OCRConfig,
    OCRFlag,
    OCRFlagStatus,
    OCRPage,
    OCRResult,
    OCRWord,
)
