"""Tests for core/keyframe_extractor.py — KeyframeExtractor."""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.keyframe_extractor import KeyframeExtractor, SceneKeyframe
from core.scene_detector import SceneBoundary


@pytest.fixture
def scenes():
    return [
        SceneBoundary(0, 0.0, 10.0, 5.0),
        SceneBoundary(1, 10.0, 20.0, 15.0),
        SceneBoundary(2, 20.0, 30.0, 25.0),
    ]


class TestKeyframeExtractor:
    async def test_extracts_one_per_scene(self, tmp_path, scenes):
        """Extract produces one keyframe per scene."""
        extractor = KeyframeExtractor()

        def mock_ffmpeg(video_path, seek, output_path):
            # Create a fake JPEG file
            output_path.write_bytes(b"\xff\xd8\xff\xe0fake")
            return None

        with patch.object(extractor, "_run_ffmpeg", side_effect=mock_ffmpeg):
            keyframes = await extractor.extract(
                Path("/fake.mp4"), scenes, tmp_path
            )

        assert len(keyframes) == 3
        for i, kf in enumerate(keyframes):
            assert kf.scene.index == i
            assert kf.extraction_error is None
            assert kf.image_path.name == f"scene_{i:03d}.jpg"

    async def test_output_filenames(self, tmp_path, scenes):
        """Output files named scene_000.jpg, scene_001.jpg, etc."""
        extractor = KeyframeExtractor()

        def mock_ffmpeg(video_path, seek, output_path):
            output_path.write_bytes(b"\xff\xd8\xff\xe0fake")
            return None

        with patch.object(extractor, "_run_ffmpeg", side_effect=mock_ffmpeg):
            keyframes = await extractor.extract(
                Path("/fake.mp4"), scenes, tmp_path
            )

        expected = ["scene_000.jpg", "scene_001.jpg", "scene_002.jpg"]
        actual = [kf.image_path.name for kf in keyframes]
        assert actual == expected

    async def test_failed_extraction_sets_error(self, tmp_path, scenes):
        """Failed ffmpeg sets extraction_error, does not raise."""
        extractor = KeyframeExtractor()

        def mock_ffmpeg(video_path, seek, output_path):
            return "ffmpeg error: something broke"

        with patch.object(extractor, "_run_ffmpeg", side_effect=mock_ffmpeg):
            keyframes = await extractor.extract(
                Path("/fake.mp4"), scenes, tmp_path
            )

        for kf in keyframes:
            assert kf.extraction_error is not None
            assert "ffmpeg error" in kf.extraction_error

    async def test_exception_in_ffmpeg_graceful(self, tmp_path, scenes):
        """Exception in ffmpeg is caught and set as extraction_error."""
        extractor = KeyframeExtractor()

        def mock_ffmpeg(video_path, seek, output_path):
            raise RuntimeError("unexpected crash")

        with patch.object(extractor, "_run_ffmpeg", side_effect=mock_ffmpeg):
            keyframes = await extractor.extract(
                Path("/fake.mp4"), scenes, tmp_path
            )

        for kf in keyframes:
            assert kf.extraction_error is not None

    async def test_output_dir_copies_frames(self, tmp_path, scenes):
        """With output_dir, frames are copied to persistent storage."""
        extractor = KeyframeExtractor()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        def mock_ffmpeg(video_path, seek, output_path):
            output_path.write_bytes(b"\xff\xd8\xff\xe0fake")
            return None

        with patch.object(extractor, "_run_ffmpeg", side_effect=mock_ffmpeg):
            keyframes = await extractor.extract(
                Path("/fake.mp4"), scenes, tmp_path / "work", output_dir
            )

        # Frames should be in _markflow/frames/
        frames_dir = output_dir / "_markflow" / "frames"
        assert frames_dir.exists()
        for kf in keyframes:
            assert kf.image_path.parent == frames_dir

    async def test_no_output_dir_stays_in_tmp(self, tmp_path, scenes):
        """Without output_dir, frames stay in tmp only."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        extractor = KeyframeExtractor()

        def mock_ffmpeg(video_path, seek, output_path):
            output_path.write_bytes(b"\xff\xd8\xff\xe0fake")
            return None

        with patch.object(extractor, "_run_ffmpeg", side_effect=mock_ffmpeg):
            keyframes = await extractor.extract(
                Path("/fake.mp4"), scenes, work_dir, output_dir=None
            )

        for kf in keyframes:
            assert kf.image_path.parent == work_dir
