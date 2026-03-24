"""Tests for the OCR confidence pre-scan in bulk_worker."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from core.bulk_worker import (
    _estimate_ocr_confidence,
    _prescan_pdf_sync,
)


# ── _estimate_ocr_confidence tests ──────────────────────────────────────────


async def test_non_pdf_returns_none(tmp_path):
    """Non-PDF file (DOCX) returns None."""
    docx = tmp_path / "test.docx"
    docx.write_bytes(b"fake docx")
    result = await _estimate_ocr_confidence(docx)
    assert result is None


async def test_non_pdf_txt_returns_none(tmp_path):
    """Non-PDF text file returns None."""
    txt = tmp_path / "notes.txt"
    txt.write_text("hello world")
    result = await _estimate_ocr_confidence(txt)
    assert result is None


async def test_text_native_pdf_returns_high_confidence():
    """Text-native PDF returns estimated confidence >= 95.0."""
    # Mock pdfplumber to return text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "A" * 200  # 200 chars = well above 50 threshold

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page, mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = _prescan_pdf_sync(Path("test.pdf"))

    assert result is not None
    assert result >= 95.0


async def test_image_only_pdf_returns_osd_confidence():
    """Image-only PDF returns estimated confidence from OSD (mocked Tesseract)."""
    # Mock pdfplumber to return empty text (image-only)
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf), \
         patch("core.bulk_worker._osd_confidence", return_value=42.5):
        result = _prescan_pdf_sync(Path("scanned.pdf"))

    assert result is not None
    assert result == 42.5


async def test_unreadable_pdf_returns_none():
    """Unreadable PDF returns None (not an error)."""
    # Mock pdfplumber to raise an exception
    with patch("pdfplumber.open", side_effect=Exception("corrupt PDF")):
        result = _prescan_pdf_sync(Path("broken.pdf"))

    assert result is None


async def test_prescan_only_examines_first_3_pages():
    """Pre-scan only examines first 3 pages, not more."""
    call_count = 0

    class MockPage:
        def extract_text(self):
            nonlocal call_count
            call_count += 1
            return "A" * 100  # text-native

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [MockPage() for _ in range(10)]  # 10 pages

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = _prescan_pdf_sync(Path("long.pdf"))

    assert result == 95.0
    assert call_count == 3  # only first 3 pages examined


async def test_empty_pdf_returns_none():
    """PDF with 0 pages returns None."""
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = []

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = _prescan_pdf_sync(Path("empty.pdf"))

    assert result is None


async def test_estimate_ocr_confidence_pdf_integration(tmp_path):
    """_estimate_ocr_confidence calls _prescan_pdf_sync for .pdf files."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake pdf")

    with patch("core.bulk_worker._prescan_pdf_sync", return_value=88.0) as mock:
        result = await _estimate_ocr_confidence(pdf)

    assert result == 88.0
    mock.assert_called_once_with(pdf)


async def test_estimate_ocr_confidence_handles_prescan_exception(tmp_path):
    """If _prescan_pdf_sync raises, returns None instead of crashing."""
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"bad")

    with patch("core.bulk_worker._prescan_pdf_sync", side_effect=RuntimeError("boom")):
        result = await _estimate_ocr_confidence(pdf)

    assert result is None


async def test_sparse_text_pdf_below_threshold():
    """PDF with sparse text (< 50 chars/page) tries OSD."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hi"  # 2 chars — below 50

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf), \
         patch("core.bulk_worker._osd_confidence", return_value=60.0) as osd_mock:
        result = _prescan_pdf_sync(Path("sparse.pdf"))

    assert result == 60.0
    osd_mock.assert_called_once()
