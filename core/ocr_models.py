"""
OCR data models for MarkFlow.

Dataclasses representing the output of the OCR pipeline:
  OCRWord    — a single recognised word with confidence + bounding box
  OCRFlag    — a grouped region of low-confidence words awaiting review
  OCRPage    — all words and flags extracted from one page image
  OCRConfig  — runtime options (threshold, language, PSM/OEM, unattended mode)
  OCRResult  — full result for a multi-page document
"""

from dataclasses import dataclass, field
from enum import Enum


class OCRFlagStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"      # User accepted OCR output as-is
    EDITED = "edited"          # User corrected the text
    SKIPPED = "skipped"        # User skipped — placeholder left in markdown


@dataclass
class OCRWord:
    text: str
    confidence: float                       # 0.0–100.0 from Tesseract
    bbox: tuple[int, int, int, int]         # (x1, y1, x2, y2) pixel coords
    line_num: int
    word_num: int


@dataclass
class OCRFlag:
    flag_id: str                            # UUID
    batch_id: str
    file_name: str
    page_num: int
    region_bbox: tuple[int, int, int, int]  # encompasses all flagged words
    ocr_text: str                           # Tesseract's best guess
    confidence: float                       # average confidence of flagged words
    corrected_text: str | None = None
    status: OCRFlagStatus = OCRFlagStatus.PENDING
    image_path: str | None = None           # path to cropped region PNG


@dataclass
class OCRPage:
    page_num: int
    words: list[OCRWord] = field(default_factory=list)
    flags: list[OCRFlag] = field(default_factory=list)
    full_text: str = ""
    average_confidence: float = 0.0
    image_path: str | None = None           # path to the full page image


@dataclass
class OCRConfig:
    confidence_threshold: float = 80.0     # flag words below this score
    language: str = "eng"
    psm: int = 6                            # page segmentation mode
    oem: int = 3                            # OCR engine mode (LSTM)
    preprocess: bool = True                 # run deskew + denoise
    unattended: bool = False                # auto-accept all flags without review


@dataclass
class OCRResult:
    pages: list[OCRPage] = field(default_factory=list)
    total_words: int = 0
    flagged_words: int = 0
    average_confidence: float = 0.0
    flags: list[OCRFlag] = field(default_factory=list)
