"""Tests for the Adobe file indexer."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.adobe_indexer import AdobeIndexer, AdobeIndexResult, MAX_TEXT_BYTES
from core.database import init_db, get_adobe_index_entry


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


@pytest.fixture
def indexer():
    return AdobeIndexer()


# ── AI file tests ────────────────────────────────────────────────────────────


async def test_index_ai_file_metadata_only(indexer, tmp_path):
    """AI file: at minimum metadata is extracted; text extraction is best-effort."""
    ai_file = tmp_path / "test.ai"
    ai_file.write_bytes(b"fake AI file")

    with patch.object(indexer, "_extract_metadata", new_callable=AsyncMock) as mock_meta:
        mock_meta.return_value = {"Title": "Test AI", "Creator": "Illustrator"}

        # The real pdfplumber will fail on fake data, which is fine — text extraction is best-effort
        result = await indexer.index_file(ai_file)

    assert result.success
    assert result.file_ext == ".ai"
    assert result.metadata["Title"] == "Test AI"

    entry = await get_adobe_index_entry(str(ai_file))
    assert entry is not None


async def test_index_ai_with_mock_pdfplumber(indexer, tmp_path):
    """AI file with mocked pdfplumber returns text layers."""
    ai_file = tmp_path / "test.ai"
    ai_file.write_bytes(b"fake AI file")

    with patch.object(indexer, "_extract_metadata", new_callable=AsyncMock) as mock_meta:
        mock_meta.return_value = {"Title": "Test AI"}

        with patch.object(indexer, "_index_ai", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = ({"Title": "Test AI"}, ["Page 1 text"])
            result = await indexer.index_file(ai_file)

    assert result.success
    assert result.text_layers == ["Page 1 text"]


# ── PSD file tests ───────────────────────────────────────────────────────────


async def test_index_psd_file_metadata(indexer, tmp_path):
    """PSD file: at minimum metadata is extracted."""
    psd_file = tmp_path / "logo.psd"
    psd_file.write_bytes(b"fake PSD file")

    with patch.object(indexer, "_extract_metadata", new_callable=AsyncMock) as mock_meta:
        mock_meta.return_value = {"Title": "Logo", "Creator": "Photoshop"}

        # psd-tools will fail on fake data — that's ok, text extraction is best-effort
        result = await indexer.index_file(psd_file)

    assert result.success
    assert result.file_ext == ".psd"
    assert result.metadata["Title"] == "Logo"


async def test_index_psd_with_mock_text_layers(indexer, tmp_path):
    """PSD file with mocked text layer extraction."""
    psd_file = tmp_path / "logo.psd"
    psd_file.write_bytes(b"fake PSD file")

    with patch.object(indexer, "_index_psd", new_callable=AsyncMock) as mock_psd:
        mock_psd.return_value = ({"Title": "Logo"}, ["Hello World", "Layer 2"])
        result = await indexer.index_file(psd_file)

    assert result.success
    assert result.text_layers == ["Hello World", "Layer 2"]


# ── Metadata-only format tests ──────────────────────────────────────────────


async def test_index_metadata_only_formats(indexer, tmp_path):
    """INDD, AEP, PRPROJ, XD: metadata only, no text extraction."""
    for ext in (".indd", ".aep", ".prproj", ".xd"):
        path = tmp_path / f"test{ext}"
        path.write_bytes(b"fake file")

        with patch.object(indexer, "_extract_metadata", new_callable=AsyncMock) as mock_meta:
            mock_meta.return_value = {"Title": f"Test {ext}", "FileType": ext[1:].upper()}
            result = await indexer.index_file(path)

        assert result.success, f"Failed for {ext}"
        assert result.file_ext == ext
        assert result.text_layers == []
        assert result.metadata.get("Title") == f"Test {ext}"


# ── Error handling tests ────────────────────────────────────────────────────


async def test_corrupt_file_returns_failure(indexer, tmp_path):
    """Corrupt file should return success=False, not raise."""
    bad_file = tmp_path / "corrupt.ai"
    bad_file.write_bytes(b"definitely not an AI file")

    with patch.object(indexer, "_extract_metadata", new_callable=AsyncMock) as mock_meta:
        mock_meta.side_effect = Exception("Totally broken")

        with patch.object(indexer, "_index_ai", new_callable=AsyncMock) as mock_ai:
            mock_ai.side_effect = Exception("Totally broken")
            result = await indexer.index_file(bad_file)

    assert not result.success
    assert result.error_msg is not None
    assert "Totally broken" in result.error_msg


async def test_nonexistent_file(indexer):
    """Nonexistent file returns success=False."""
    result = await indexer.index_file(Path("/nonexistent/file.psd"))
    assert not result.success
    assert "Cannot stat file" in result.error_msg


async def test_unsupported_extension(indexer, tmp_path):
    """Unsupported extension returns success=False."""
    path = tmp_path / "test.jpg"
    path.write_bytes(b"jpeg data")
    result = await indexer.index_file(path)
    assert not result.success
    assert "Unsupported" in result.error_msg


# ── Text truncation tests ───────────────────────────────────────────────────


def test_truncate_text_under_limit():
    texts = ["short text", "another short"]
    result = AdobeIndexer._truncate_text(texts)
    assert result == texts


def test_truncate_text_over_limit():
    large_text = "x" * (MAX_TEXT_BYTES + 100)
    texts = [large_text]
    result = AdobeIndexer._truncate_text(texts)
    assert len(result) == 0


def test_truncate_drops_last_layers_first():
    chunk = "a" * (MAX_TEXT_BYTES // 2)
    texts = [chunk, chunk, chunk]
    result = AdobeIndexer._truncate_text(texts)
    assert len(result) == 2


# ── Exiftool tests ───────────────────────────────────────────────────────────


async def test_extract_metadata_exiftool_not_found(indexer, tmp_path):
    """If exiftool is not installed, return error dict."""
    path = tmp_path / "test.psd"
    path.write_bytes(b"data")

    with patch("core.adobe_indexer.subprocess.run", side_effect=FileNotFoundError):
        meta = await indexer._extract_metadata(path)

    assert "_error" in meta
    assert "not installed" in meta["_error"]


async def test_extract_metadata_exiftool_timeout(indexer, tmp_path):
    """Exiftool timeout returns error dict."""
    import subprocess
    path = tmp_path / "test.psd"
    path.write_bytes(b"data")

    with patch("core.adobe_indexer.subprocess.run", side_effect=subprocess.TimeoutExpired("exiftool", 30)):
        meta = await indexer._extract_metadata(path)

    assert "_error" in meta
    assert "timeout" in meta["_error"]


async def test_result_upserted_to_db(indexer, tmp_path):
    """Successful indexing upserts entry to adobe_index table."""
    path = tmp_path / "test.indd"
    path.write_bytes(b"fake indd")

    with patch.object(indexer, "_extract_metadata", new_callable=AsyncMock) as mock_meta:
        mock_meta.return_value = {"Title": "Design"}
        result = await indexer.index_file(path)

    assert result.success
    entry = await get_adobe_index_entry(str(path))
    assert entry is not None
    assert entry["file_ext"] == ".indd"
