"""
Keyframe extraction — extracts a single JPEG frame at the midpoint of each scene.

Uses ffmpeg to seek to scene midpoints and extract frames. All extractions run
concurrently with a semaphore to prevent I/O contention.
"""

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

from core.scene_detector import SceneBoundary

log = structlog.get_logger(__name__)


@dataclass
class SceneKeyframe:
    scene: SceneBoundary
    image_path: Path
    extraction_error: str | None = None


class KeyframeExtractor:
    async def extract(
        self,
        video_path: Path,
        scenes: list[SceneBoundary],
        tmp_dir: Path,
        output_dir: Path | None = None,
    ) -> list[SceneKeyframe]:
        """
        Extract one JPEG per scene at the scene's midpoint_seconds.
        Up to 4 concurrent extractions. Failed extractions set extraction_error.
        If output_dir is provided, copies frames there for persistent storage.
        """
        semaphore = asyncio.Semaphore(4)
        tasks = [
            self._extract_one(video_path, scene, tmp_dir, semaphore)
            for scene in scenes
        ]
        keyframes = await asyncio.gather(*tasks)

        # Copy to persistent storage if requested
        if output_dir:
            frames_dir = output_dir / "_markflow" / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            for kf in keyframes:
                if kf.extraction_error is None and kf.image_path.exists():
                    dest = frames_dir / kf.image_path.name
                    try:
                        shutil.copy2(kf.image_path, dest)
                        kf.image_path = dest
                    except Exception as exc:
                        log.warning(
                            "keyframe_copy_failed",
                            src=str(kf.image_path),
                            dest=str(dest),
                            error=str(exc),
                        )

        return keyframes

    async def _extract_one(
        self,
        video_path: Path,
        scene: SceneBoundary,
        tmp_dir: Path,
        semaphore: asyncio.Semaphore,
    ) -> SceneKeyframe:
        filename = f"scene_{scene.index:03d}.jpg"
        output_path = tmp_dir / filename

        async with semaphore:
            try:
                result = await asyncio.to_thread(
                    self._run_ffmpeg, video_path, scene.midpoint_seconds, output_path
                )
                if result is not None:
                    return SceneKeyframe(scene=scene, image_path=output_path, extraction_error=result)
                if not output_path.exists():
                    return SceneKeyframe(
                        scene=scene,
                        image_path=output_path,
                        extraction_error="ffmpeg produced no output",
                    )
                return SceneKeyframe(scene=scene, image_path=output_path)
            except Exception as exc:
                log.warning(
                    "keyframe_extract_failed",
                    scene=scene.index,
                    error=str(exc),
                )
                return SceneKeyframe(
                    scene=scene,
                    image_path=output_path,
                    extraction_error=str(exc),
                )

    def _run_ffmpeg(
        self, video_path: Path, seek_seconds: float, output_path: Path
    ) -> str | None:
        """Run ffmpeg to extract a single frame. Returns error string or None."""
        cmd = [
            "ffmpeg",
            "-ss", str(seek_seconds),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "3",
            str(output_path),
            "-y",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=30,
            )
            return None
        except subprocess.TimeoutExpired:
            return "ffmpeg timeout (30s)"
        except subprocess.CalledProcessError as exc:
            return f"ffmpeg error: {exc.stderr.decode(errors='replace')[:200]}"
