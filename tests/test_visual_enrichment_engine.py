"""Tests for core/visual_enrichment_engine.py — VisualEnrichmentEngine."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.scene_detector import SceneBoundary
from core.keyframe_extractor import SceneKeyframe
from core.vision_adapter import FrameDescription
from core.visual_enrichment_engine import EnrichmentResult, VisualEnrichmentEngine


@pytest.fixture
def mock_scenes():
    return [
        SceneBoundary(0, 0.0, 10.0, 5.0),
        SceneBoundary(1, 10.0, 20.0, 15.0),
    ]


@pytest.fixture
def mock_keyframes(mock_scenes, tmp_path):
    kfs = []
    for scene in mock_scenes:
        p = tmp_path / f"scene_{scene.index:03d}.jpg"
        p.write_bytes(b"\xff\xd8fake")
        kfs.append(SceneKeyframe(scene=scene, image_path=p))
    return kfs


class TestVisualEnrichmentEngine:
    @patch("core.visual_enrichment_engine.get_preference")
    @patch("core.visual_enrichment_engine.SceneDetector")
    @patch("core.visual_enrichment_engine.KeyframeExtractor")
    @patch("core.visual_enrichment_engine.get_active_provider")
    async def test_level_2_no_descriptions(
        self, mock_get_provider, mock_kf_cls, mock_sd_cls, mock_pref, mock_scenes, mock_keyframes, tmp_path
    ):
        """Enrichment level 2 produces scenes+keyframes but no descriptions."""
        mock_pref.side_effect = lambda key: {
            "vision_enrichment_level": "2",
            "vision_frame_limit": "50",
            "vision_save_keyframes": "false",
            "vision_frame_prompt": "describe",
        }.get(key)

        mock_detector = AsyncMock()
        mock_detector.detect = AsyncMock(return_value=mock_scenes)
        mock_sd_cls.return_value = mock_detector

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=mock_keyframes)
        mock_kf_cls.return_value = mock_extractor

        engine = VisualEnrichmentEngine()
        result = await engine.enrich(Path("/fake.mp4"), 20.0, tmp_path, tmp_path / "out")

        assert isinstance(result, EnrichmentResult)
        assert result.enrichment_level == 2
        assert result.total_scenes == 2
        assert result.descriptions == []
        assert result.described_scenes == 0
        mock_get_provider.assert_not_called()

    @patch("core.visual_enrichment_engine.get_preference")
    @patch("core.visual_enrichment_engine.SceneDetector")
    @patch("core.visual_enrichment_engine.KeyframeExtractor")
    @patch("core.visual_enrichment_engine.get_active_provider")
    @patch("core.visual_enrichment_engine.VisionAdapter")
    async def test_level_3_with_provider(
        self, mock_adapter_cls, mock_get_provider, mock_kf_cls, mock_sd_cls, mock_pref, mock_scenes, mock_keyframes, tmp_path
    ):
        """Level 3 with active provider calls describe_frame for each keyframe."""
        mock_pref.side_effect = lambda key: {
            "vision_enrichment_level": "3",
            "vision_frame_limit": "50",
            "vision_save_keyframes": "false",
            "vision_frame_prompt": "describe this",
        }.get(key)

        mock_detector = AsyncMock()
        mock_detector.detect = AsyncMock(return_value=mock_scenes)
        mock_sd_cls.return_value = mock_detector

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=mock_keyframes)
        mock_kf_cls.return_value = mock_extractor

        mock_get_provider.return_value = {
            "provider": "openai", "model": "gpt-4o", "api_key": "sk-test", "api_base_url": ""
        }

        mock_adapter = AsyncMock()
        mock_adapter.supports_vision.return_value = True
        mock_adapter._provider = "openai"
        mock_adapter._model = "gpt-4o"
        mock_adapter.describe_frame = AsyncMock(side_effect=[
            FrameDescription(0, "A slide", "openai", "gpt-4o"),
            FrameDescription(1, "A chart", "openai", "gpt-4o"),
        ])
        mock_adapter_cls.return_value = mock_adapter

        engine = VisualEnrichmentEngine()
        result = await engine.enrich(Path("/fake.mp4"), 20.0, tmp_path, tmp_path / "out")

        assert result.enrichment_level == 3
        assert result.described_scenes == 2
        assert result.failed_scenes == 0
        assert len(result.descriptions) == 2
        assert result.provider_id == "openai"

    @patch("core.visual_enrichment_engine.get_preference")
    @patch("core.visual_enrichment_engine.SceneDetector")
    @patch("core.visual_enrichment_engine.KeyframeExtractor")
    @patch("core.visual_enrichment_engine.get_active_provider")
    async def test_level_3_no_provider(
        self, mock_get_provider, mock_kf_cls, mock_sd_cls, mock_pref, mock_scenes, mock_keyframes, tmp_path
    ):
        """Level 3 without active provider skips descriptions gracefully."""
        mock_pref.side_effect = lambda key: {
            "vision_enrichment_level": "3",
            "vision_frame_limit": "50",
            "vision_save_keyframes": "false",
            "vision_frame_prompt": "describe",
        }.get(key)

        mock_detector = AsyncMock()
        mock_detector.detect = AsyncMock(return_value=mock_scenes)
        mock_sd_cls.return_value = mock_detector

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=mock_keyframes)
        mock_kf_cls.return_value = mock_extractor

        mock_get_provider.return_value = None

        engine = VisualEnrichmentEngine()
        result = await engine.enrich(Path("/fake.mp4"), 20.0, tmp_path, tmp_path / "out")

        assert result.enrichment_level == 3
        assert result.descriptions == []
        assert result.provider_id is None

    @patch("core.visual_enrichment_engine.get_preference")
    @patch("core.visual_enrichment_engine.SceneDetector")
    @patch("core.visual_enrichment_engine.KeyframeExtractor")
    @patch("core.visual_enrichment_engine.get_active_provider")
    @patch("core.visual_enrichment_engine.VisionAdapter")
    async def test_failed_keyframe_skips_api_call(
        self, mock_adapter_cls, mock_get_provider, mock_kf_cls, mock_sd_cls, mock_pref, mock_scenes, tmp_path
    ):
        """Failed keyframe extraction produces error description without API call."""
        mock_pref.side_effect = lambda key: {
            "vision_enrichment_level": "3",
            "vision_frame_limit": "50",
            "vision_save_keyframes": "false",
            "vision_frame_prompt": "describe",
        }.get(key)

        mock_detector = AsyncMock()
        mock_detector.detect = AsyncMock(return_value=mock_scenes)
        mock_sd_cls.return_value = mock_detector

        # One failed keyframe, one successful
        failed_kf = SceneKeyframe(
            scene=mock_scenes[0],
            image_path=tmp_path / "scene_000.jpg",
            extraction_error="ffmpeg timeout",
        )
        good_kf_path = tmp_path / "scene_001.jpg"
        good_kf_path.write_bytes(b"\xff\xd8")
        good_kf = SceneKeyframe(scene=mock_scenes[1], image_path=good_kf_path)

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=[failed_kf, good_kf])
        mock_kf_cls.return_value = mock_extractor

        mock_get_provider.return_value = {
            "provider": "openai", "model": "gpt-4o", "api_key": "sk-test", "api_base_url": ""
        }

        mock_adapter = AsyncMock()
        mock_adapter.supports_vision.return_value = True
        mock_adapter._provider = "openai"
        mock_adapter._model = "gpt-4o"
        mock_adapter.describe_frame = AsyncMock(
            return_value=FrameDescription(1, "Some description", "openai", "gpt-4o")
        )
        mock_adapter_cls.return_value = mock_adapter

        engine = VisualEnrichmentEngine()
        result = await engine.enrich(Path("/fake.mp4"), 20.0, tmp_path, tmp_path / "out")

        assert result.described_scenes == 1
        assert result.failed_scenes == 1
        # API should only have been called once (for the good keyframe)
        assert mock_adapter.describe_frame.call_count == 1
