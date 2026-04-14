"""
Local Whisper transcription with lazy model loading and GPU auto-detection.

The model is loaded on first transcription call, NOT at startup, to avoid
blocking the FastAPI lifespan handler (loading takes 5-30s depending on size).

GPU auto-detection:
  - torch.cuda.is_available() → use CUDA
  - Otherwise → CPU
  - User can override via whisper_device preference ("auto", "cpu", "cuda")
"""

import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import torch

log = structlog.get_logger(__name__)

# Single-flight gate for Whisper inference.
#
# Python threads cannot be cancelled, so a timed-out transcription (via
# ``asyncio.wait_for``) continues running in the background, consuming the
# GPU/CPU until the underlying ``model.transcribe`` returns. The fix uses
# TWO locks:
#
#   _thread_lock (threading.Lock): held INSIDE the worker thread for the
#     entire duration of ``model.transcribe``. An orphan thread (from a
#     prior timeout) holds this until it finishes, so the next worker
#     thread blocks at ``_thread_lock.acquire()`` rather than contending
#     with the orphan on the GPU.
#
#   _asyncio_lock (asyncio.Lock): held by the coroutine across the whole
#     ``asyncio.to_thread`` call. On CancelledError (wait_for timeout),
#     this lock releases immediately, freeing the awaiter — but the next
#     coroutine still blocks on _thread_lock inside its own worker thread
#     before touching the model. Net effect: at most one real Whisper
#     inference runs at any moment, even under repeated timeouts.
_thread_lock = threading.Lock()
_asyncio_lock = asyncio.Lock()

# True while any worker thread is actively inside ``model.transcribe``.
# Exposed for diagnostics — a timed-out caller can check this to know
# whether their GPU is still occupied by the orphan job.
_orphan_thread_active = False


def orphan_thread_active() -> bool:
    """Return True if a previous timed-out Whisper job is still running."""
    return _orphan_thread_active


@dataclass
class TranscriptionSegment:
    """Single segment of transcribed text."""

    index: int
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None
    confidence: float | None = None


@dataclass
class TranscriptionResult:
    """Complete transcription result."""

    segments: list[TranscriptionSegment] = field(default_factory=list)
    language: str | None = None
    duration_seconds: float | None = None
    engine: str = "whisper_local"
    model_name: str | None = None
    word_count: int = 0
    raw_text: str = ""


class WhisperTranscriber:
    """
    Local Whisper transcription with lazy model loading.

    Model is cached as class-level state so it persists across calls
    without reloading. Reloaded only if model name or device changes.
    """

    _model = None
    _model_name: str | None = None
    _device: str | None = None

    @classmethod
    def _resolve_device(cls, preference: str = "auto") -> str:
        """Determine compute device: auto-detect GPU or use preference."""
        if preference == "cuda":
            if torch.cuda.is_available():
                return "cuda"
            log.warning("whisper_cuda_requested_but_unavailable")
            return "cpu"
        elif preference == "cpu":
            return "cpu"
        else:  # auto
            device = "cuda" if torch.cuda.is_available() else "cpu"
            log.info(
                "whisper_device_auto",
                device=device,
                cuda_available=torch.cuda.is_available(),
            )
            return device

    @classmethod
    def _load_model(cls, model_name: str = "base", device: str = "auto"):
        """Load Whisper model (lazy, cached)."""
        import whisper  # lazy import — whisper is heavy

        resolved_device = cls._resolve_device(device)

        if (
            cls._model is not None
            and cls._model_name == model_name
            and cls._device == resolved_device
        ):
            return cls._model  # already loaded with same config

        log.info("whisper_loading_model", model=model_name, device=resolved_device)
        cls._model = whisper.load_model(model_name, device=resolved_device)
        cls._model_name = model_name
        cls._device = resolved_device
        log.info("whisper_model_loaded", model=model_name, device=resolved_device)
        return cls._model

    @classmethod
    async def transcribe(
        cls,
        audio_path: Path,
        model_name: str = "base",
        language: str | None = None,
        device: str = "auto",
    ) -> TranscriptionResult:
        """
        Transcribe audio file using local Whisper.
        Runs in a thread pool to avoid blocking the event loop.
        """

        def _run():
            global _orphan_thread_active
            # Block here if a prior orphan thread is still running. This
            # is the GPU-level serialization that outlives asyncio.
            with _thread_lock:
                _orphan_thread_active = True
                try:
                    model = cls._load_model(model_name, device)
                    options = {}
                    if language and language != "auto":
                        options["language"] = language

                    return model.transcribe(str(audio_path), **options)
                finally:
                    _orphan_thread_active = False

        async with _asyncio_lock:
            try:
                raw = await asyncio.to_thread(_run)
            except asyncio.CancelledError:
                log.warning(
                    "whisper_orphan_thread",
                    note="Inference thread cannot be cancelled; it will "
                         "continue running until model.transcribe returns. "
                         "Subsequent Whisper jobs will queue behind it at "
                         "the threading.Lock boundary.",
                    file=str(audio_path),
                )
                raise

        segments = []
        total_text = []
        for i, seg in enumerate(raw.get("segments", [])):
            segments.append(
                TranscriptionSegment(
                    index=i,
                    start_seconds=seg["start"],
                    end_seconds=seg["end"],
                    text=seg["text"].strip(),
                    confidence=seg.get("avg_logprob"),
                )
            )
            total_text.append(seg["text"].strip())

        full_text = " ".join(total_text)
        last_end = raw["segments"][-1]["end"] if raw.get("segments") else None

        return TranscriptionResult(
            segments=segments,
            language=raw.get("language"),
            duration_seconds=last_end,
            engine="whisper_local",
            model_name=model_name,
            word_count=len(full_text.split()) if full_text else 0,
            raw_text=full_text,
        )

    @classmethod
    def is_available(cls) -> bool:
        """Check if Whisper is installed and usable."""
        try:
            import whisper  # noqa: F401

            return True
        except ImportError:
            return False

    @classmethod
    def get_device_info(cls) -> dict:
        """Return GPU/device info for health checks."""
        return {
            "whisper_available": cls.is_available(),
            "cuda_available": torch.cuda.is_available(),
            "device": cls._device or "not loaded",
            "model_loaded": cls._model_name,
            "gpu_name": (
                torch.cuda.get_device_name(0)
                if torch.cuda.is_available()
                else None
            ),
        }
