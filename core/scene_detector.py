"""
Scene boundary detection using PySceneDetect.

Detects cuts/transitions in video files and returns a list of scene boundaries
with start, end, and midpoint timestamps. Used by VisualEnrichmentEngine to
determine where to extract keyframes.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


@dataclass
class SceneBoundary:
    index: int
    start_seconds: float
    end_seconds: float
    midpoint_seconds: float


class SceneDetector:
    def __init__(self, frame_limit: int = 50):
        self._frame_limit = max(1, frame_limit)

    async def detect(self, video_path: Path, duration: float = 0.0) -> list[SceneBoundary]:
        """
        Run PySceneDetect on the video in a thread.
        Returns list of SceneBoundary, sorted by start_seconds.
        Never raises -- returns single-scene fallback on any error.
        """
        try:
            raw_scenes = await asyncio.to_thread(self._detect_sync, video_path)
        except Exception as exc:
            log.warning("scene_detector.failed", path=str(video_path), error=str(exc))
            raw_scenes = []

        if not raw_scenes:
            # Single-scene fallback covering the entire video
            mid = duration / 2 if duration > 0 else 0.0
            return [SceneBoundary(index=0, start_seconds=0.0, end_seconds=duration, midpoint_seconds=mid)]

        scenes = self._build_scenes(raw_scenes, duration)
        if len(scenes) > self._frame_limit:
            scenes = self._downsample(scenes)
        # Re-index after potential downsampling
        for i, s in enumerate(scenes):
            s.index = i
        return scenes

    def _detect_sync(self, video_path: Path) -> list[tuple]:
        """Synchronous PySceneDetect call."""
        from scenedetect import detect, ContentDetector

        scene_list = detect(str(video_path), ContentDetector())
        return scene_list

    def _build_scenes(self, raw_scenes: list, duration: float) -> list[SceneBoundary]:
        """Convert PySceneDetect tuples to SceneBoundary list."""
        scenes = []
        for i, (start_tc, end_tc) in enumerate(raw_scenes):
            start = start_tc.get_seconds()
            end = end_tc.get_seconds()
            mid = (start + end) / 2
            scenes.append(SceneBoundary(index=i, start_seconds=start, end_seconds=end, midpoint_seconds=mid))

        # Ensure last scene extends to actual duration if known
        if duration > 0 and scenes and scenes[-1].end_seconds < duration:
            scenes[-1].end_seconds = duration
            scenes[-1].midpoint_seconds = (scenes[-1].start_seconds + duration) / 2

        return scenes

    def _downsample(self, scenes: list[SceneBoundary]) -> list[SceneBoundary]:
        """Evenly sample scenes down to frame_limit, keeping first and last."""
        if len(scenes) <= self._frame_limit:
            return scenes
        if self._frame_limit == 1:
            return [scenes[0]]
        if self._frame_limit == 2:
            return [scenes[0], scenes[-1]]

        # Keep first and last, sample evenly from the middle
        middle_count = self._frame_limit - 2
        middle = scenes[1:-1]
        step = len(middle) / middle_count
        sampled = [scenes[0]]
        for i in range(middle_count):
            idx = int(i * step)
            sampled.append(middle[idx])
        sampled.append(scenes[-1])
        return sampled
