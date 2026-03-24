"""
Visual enrichment engine — orchestrates scene detection, keyframe extraction,
and optional AI frame descriptions for video files.

Per Conflict Analysis: uses VisionAdapter (existing LLM provider system) instead
of a separate vision_providers package. Vision uses whatever provider is already
active in the LLM provider system.
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from core.database import get_active_provider, get_preference
from core.keyframe_extractor import KeyframeExtractor, SceneKeyframe
from core.scene_detector import SceneBoundary, SceneDetector
from core.vision_adapter import FrameDescription, VisionAdapter

log = structlog.get_logger(__name__)


@dataclass
class EnrichmentResult:
    scenes: list[SceneBoundary] = field(default_factory=list)
    keyframes: list[SceneKeyframe] = field(default_factory=list)
    descriptions: list[FrameDescription] = field(default_factory=list)
    provider_id: str | None = None
    model: str | None = None
    enrichment_level: int = 2
    total_scenes: int = 0
    described_scenes: int = 0
    failed_scenes: int = 0


class VisualEnrichmentEngine:
    """Orchestrates the full visual enrichment pipeline for video files."""

    async def enrich(
        self,
        video_path: Path,
        duration_seconds: float,
        tmp_dir: Path,
        output_dir: Path,
    ) -> EnrichmentResult:
        """
        Full visual enrichment pipeline:
        1. Read preferences for enrichment settings
        2. Scene detection (always runs for video)
        3. Keyframe extraction (always runs for video)
        4. Frame description (only if active provider exists and level >= 3)
        """
        # Read settings from preferences
        level_str = await get_preference("vision_enrichment_level") or "2"
        level = int(level_str) if level_str.isdigit() else 2
        frame_limit_str = await get_preference("vision_frame_limit") or "50"
        frame_limit = int(frame_limit_str) if frame_limit_str.isdigit() else 50
        save_keyframes_str = await get_preference("vision_save_keyframes") or "false"
        save_keyframes = save_keyframes_str.lower() == "true"
        prompt = await get_preference("vision_frame_prompt") or (
            "Describe this frame from a video. Note any visible text, slides, "
            "diagrams, charts, people, or on-screen graphics. Be concise and "
            "factual. Do not describe what you cannot see clearly."
        )

        result = EnrichmentResult(enrichment_level=level)

        # Step 1: Scene detection
        detector = SceneDetector(frame_limit=frame_limit)
        scenes = await detector.detect(video_path, duration=duration_seconds)
        result.scenes = scenes
        result.total_scenes = len(scenes)

        # Step 2: Keyframe extraction
        persistent_dir = output_dir if save_keyframes else None
        extractor = KeyframeExtractor()
        keyframes = await extractor.extract(video_path, scenes, tmp_dir, persistent_dir)
        result.keyframes = keyframes

        # Step 3: Frame description (only if level >= 3 and provider available)
        if level >= 3:
            provider_config = await get_active_provider()
            if provider_config:
                adapter = VisionAdapter(provider_config)
                if adapter.supports_vision():
                    result.provider_id = provider_config.get("provider")
                    result.model = provider_config.get("model")
                    descriptions = await self._describe_all(adapter, keyframes, prompt)
                    result.descriptions = descriptions
                    result.described_scenes = sum(
                        1 for d in descriptions if d.error is None
                    )
                    result.failed_scenes = sum(
                        1 for d in descriptions if d.error is not None
                    )
                else:
                    log.info(
                        "vision_enrichment.provider_no_vision",
                        provider=provider_config.get("provider"),
                    )
            else:
                log.info("vision_enrichment.no_active_provider")

        return result

    async def _describe_all(
        self,
        adapter: VisionAdapter,
        keyframes: list[SceneKeyframe],
        prompt: str,
    ) -> list[FrameDescription]:
        """
        Describe all keyframes concurrently with semaphore(3).
        Failed keyframes (extraction_error set) produce a FrameDescription
        with error set without calling the API.
        """
        semaphore = asyncio.Semaphore(3)

        async def _describe_one(kf: SceneKeyframe) -> FrameDescription:
            if kf.extraction_error:
                return FrameDescription(
                    scene_index=kf.scene.index,
                    description="",
                    provider_id=adapter._provider,
                    model=adapter._model,
                    error=f"[keyframe extraction failed -- {kf.extraction_error}]",
                )
            async with semaphore:
                return await adapter.describe_frame(
                    kf.image_path, prompt, kf.scene.index
                )

        tasks = [_describe_one(kf) for kf in keyframes]
        return await asyncio.gather(*tasks)
