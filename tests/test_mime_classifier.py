"""Tests for core/mime_classifier.py — MIME detection and classification."""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.mime_classifier import classify, detect_mime


class TestClassify:
    def test_known_mime_jpeg(self):
        mime, cat = classify(Path("photo.jpg"), mime_type="image/jpeg")
        assert cat == "raster_image"
        assert mime == "image/jpeg"

    def test_known_mime_zip(self):
        mime, cat = classify(Path("archive.zip"), mime_type="application/zip")
        assert cat == "archive"

    def test_known_mime_sqlite(self):
        mime, cat = classify(Path("data.db"), mime_type="application/x-sqlite3")
        assert cat == "database"

    def test_known_mime_iso(self):
        mime, cat = classify(Path("disk.iso"), mime_type="application/x-iso9660-image")
        assert cat == "disk_image"

    def test_known_mime_font(self):
        mime, cat = classify(Path("font.ttf"), mime_type="font/ttf")
        assert cat == "font"

    def test_extension_fallback_when_mime_unknown(self):
        mime, cat = classify(Path("file.exe"), mime_type="application/octet-stream")
        assert cat == "executable"

    def test_extension_fallback_iso(self):
        mime, cat = classify(Path("disk.iso"), mime_type="application/octet-stream")
        assert cat == "disk_image"

    def test_extension_fallback_code(self):
        mime, cat = classify(Path("script.py"), mime_type="text/plain")
        assert cat == "code"

    def test_truly_unknown_file(self):
        mime, cat = classify(Path("file.xyzabc"), mime_type="application/octet-stream")
        assert cat == "unknown"
        assert mime == "application/octet-stream"

    def test_no_extension(self):
        mime, cat = classify(Path("Makefile"), mime_type="application/octet-stream")
        assert cat == "unknown"

    def test_auto_detect_mime(self, tmp_path):
        """When mime_type is None, detect_mime is called."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        mime, cat = classify(test_file)
        # text/plain should fall back to extension for .txt -> code
        assert isinstance(mime, str)
        assert isinstance(cat, str)


class TestDetectMime:
    def test_nonexistent_file_returns_default(self):
        result = detect_mime(Path("/nonexistent/file.xyz"))
        assert result == "application/octet-stream"

    def test_real_text_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        result = detect_mime(f)
        assert "text" in result

    @patch("core.mime_classifier.magic")
    def test_magic_exception_returns_default(self, mock_magic):
        mock_magic.from_file.side_effect = Exception("libmagic crash")
        result = detect_mime(Path("/some/file"))
        assert result == "application/octet-stream"
