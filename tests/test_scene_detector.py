"""Tests for core/scene_detector.py — SceneDetector."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.scene_detector import SceneBoundary, SceneDetector


class TestSceneDetector:
    async def test_single_scene_fallback_when_zero_detected(self):
        """detect() returns at least 1 scene even if PySceneDetect finds 0."""
        detector = SceneDetector(frame_limit=50)
        with patch.object(detector, "_detect_sync", return_value=[]):
            scenes = await detector.detect(Path("/fake.mp4"), duration=60.0)
        assert len(scenes) == 1
        assert scenes[0].start_seconds == 0.0
        assert scenes[0].end_seconds == 60.0
        assert scenes[0].midpoint_seconds == 30.0

    async def test_fallback_on_exception(self):
        """detect() returns single-scene fallback on PySceneDetect crash."""
        detector = SceneDetector(frame_limit=50)
        with patch.object(detector, "_detect_sync", side_effect=RuntimeError("crash")):
            scenes = await detector.detect(Path("/fake.mp4"), duration=10.0)
        assert len(scenes) == 1
        assert scenes[0].end_seconds == 10.0

    async def test_multiple_scenes_returned(self):
        """detect() properly converts raw scenes to SceneBoundary."""
        detector = SceneDetector(frame_limit=50)
        # Mock PySceneDetect output format (start_tc, end_tc)
        mock_tc1_start = MagicMock()
        mock_tc1_start.get_seconds.return_value = 0.0
        mock_tc1_end = MagicMock()
        mock_tc1_end.get_seconds.return_value = 10.5
        mock_tc2_start = MagicMock()
        mock_tc2_start.get_seconds.return_value = 10.5
        mock_tc2_end = MagicMock()
        mock_tc2_end.get_seconds.return_value = 25.0

        raw_scenes = [(mock_tc1_start, mock_tc1_end), (mock_tc2_start, mock_tc2_end)]
        with patch.object(detector, "_detect_sync", return_value=raw_scenes):
            scenes = await detector.detect(Path("/fake.mp4"), duration=25.0)

        assert len(scenes) == 2
        assert scenes[0].start_seconds == 0.0
        assert scenes[0].end_seconds == 10.5
        assert scenes[0].midpoint_seconds == pytest.approx(5.25)
        assert scenes[1].start_seconds == 10.5
        assert scenes[1].end_seconds == 25.0

    async def test_frame_limit_caps_scenes(self):
        """frame_limit=3 caps scenes even when more are detected."""
        detector = SceneDetector(frame_limit=3)

        # Create 10 mock scenes
        raw_scenes = []
        for i in range(10):
            start_tc = MagicMock()
            start_tc.get_seconds.return_value = float(i * 10)
            end_tc = MagicMock()
            end_tc.get_seconds.return_value = float((i + 1) * 10)
            raw_scenes.append((start_tc, end_tc))

        with patch.object(detector, "_detect_sync", return_value=raw_scenes):
            scenes = await detector.detect(Path("/fake.mp4"), duration=100.0)

        assert len(scenes) == 3
        # First and last scenes should be preserved
        assert scenes[0].start_seconds == 0.0
        assert scenes[-1].end_seconds == 100.0

    async def test_midpoint_between_start_and_end(self):
        """midpoint_seconds always falls between start and end."""
        detector = SceneDetector(frame_limit=50)
        tc_start = MagicMock()
        tc_start.get_seconds.return_value = 5.0
        tc_end = MagicMock()
        tc_end.get_seconds.return_value = 15.0

        with patch.object(detector, "_detect_sync", return_value=[(tc_start, tc_end)]):
            scenes = await detector.detect(Path("/fake.mp4"), duration=15.0)

        for scene in scenes:
            assert scene.start_seconds <= scene.midpoint_seconds <= scene.end_seconds

    async def test_zero_duration_fallback(self):
        """Duration 0 produces a single-scene fallback."""
        detector = SceneDetector(frame_limit=50)
        with patch.object(detector, "_detect_sync", return_value=[]):
            scenes = await detector.detect(Path("/fake.mp4"), duration=0.0)
        assert len(scenes) == 1
        assert scenes[0].midpoint_seconds == 0.0

    async def test_first_and_last_preserved_when_downsampling(self):
        """Downsampling keeps the first and last scenes."""
        detector = SceneDetector(frame_limit=2)
        raw_scenes = []
        for i in range(5):
            s = MagicMock()
            s.get_seconds.return_value = float(i * 10)
            e = MagicMock()
            e.get_seconds.return_value = float((i + 1) * 10)
            raw_scenes.append((s, e))

        with patch.object(detector, "_detect_sync", return_value=raw_scenes):
            scenes = await detector.detect(Path("/fake.mp4"), duration=50.0)

        assert len(scenes) == 2
        assert scenes[0].start_seconds == 0.0
        assert scenes[-1].end_seconds == 50.0


class TestDownsample:
    def test_noop_when_under_limit(self):
        detector = SceneDetector(frame_limit=10)
        scenes = [
            SceneBoundary(i, i * 10.0, (i + 1) * 10.0, i * 10.0 + 5.0)
            for i in range(5)
        ]
        result = detector._downsample(scenes)
        assert len(result) == 5

    def test_single_limit(self):
        detector = SceneDetector(frame_limit=1)
        scenes = [
            SceneBoundary(i, i * 10.0, (i + 1) * 10.0, i * 10.0 + 5.0)
            for i in range(5)
        ]
        result = detector._downsample(scenes)
        assert len(result) == 1
        assert result[0].index == 0
