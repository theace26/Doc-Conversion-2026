"""
Cloud transcription fallback — tries all configured providers with audio
support in priority order until one succeeds.

Supported providers:
  - OpenAI: Whisper API (POST /v1/audio/transcriptions)
  - Gemini: Inline audio via generateContent
  - Anthropic: No audio support (skipped)
  - Ollama: No standard audio transcription (skipped)
"""

import base64
import json

import httpx
import structlog
from pathlib import Path

from core.storage_probe import ErrorRateMonitor
from core.whisper_transcriber import TranscriptionResult, TranscriptionSegment

log = structlog.get_logger(__name__)

# Session-level error monitor — shared across all cloud transcription calls.
# If cloud APIs fail repeatedly (expired key, rate limit, service down),
# disables cloud fallback for the rest of the session to avoid wasting time.
_cloud_error_monitor = ErrorRateMonitor(window_size=20, abort_threshold=0.6, min_ops=5)

# Provider audio support map.
#
# IMPORTANT: Anthropic (Claude) does NOT support audio transcription as of
# 2026-04-07 — Claude's API accepts text, images, and PDFs but not audio.
# If a user has ONLY Anthropic configured, there is no cloud fallback path
# for MP3/WAV/etc, and we must fail with a clear, actionable error instead
# of the generic "all cloud providers failed" message. See
# NoAudioProviderError below and docs/gotchas.md → Transcription.
AUDIO_CAPABLE_PROVIDERS = {
    "openai": True,
    "gemini": True,
    "anthropic": False,
    "ollama": False,
    "custom": False,
}


class NoAudioProviderError(RuntimeError):
    """
    Raised when cloud transcription is attempted but no configured provider
    can handle audio. Distinct from generic provider failures (rate limits,
    API errors) so the caller can render an actionable, user-facing message
    instead of a cryptic "all providers failed" stack trace.
    """


class CloudTranscriber:
    """
    Cloud transcription fallback.
    Tries providers in priority order until one succeeds.
    Uses existing LLM provider infrastructure from core/llm_providers.py.
    """

    @classmethod
    async def transcribe(
        cls,
        audio_path: Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """
        Try all configured cloud providers that support audio.

        Uses a session-level ErrorRateMonitor — if cloud APIs fail repeatedly
        (expired key, rate limit, service outage), raises immediately instead
        of wasting time on providers that are known to be down.
        """
        # Fast-fail if cloud has been unreliable this session
        if _cloud_error_monitor.should_abort():
            raise RuntimeError(
                "Cloud transcription disabled for this session: too many recent failures "
                f"({_cloud_error_monitor.total_errors} errors, "
                f"{_cloud_error_monitor.consecutive_errors} consecutive)"
            )

        from core.database import db_fetch_all

        # Get all configured providers sorted by is_active (active first)
        providers = await db_fetch_all(
            "SELECT * FROM llm_providers ORDER BY is_active DESC, name ASC"
        )

        # Pre-flight: is there ANY provider that (a) has an audio-capable type
        # and (b) has an api_key configured? If not, bail immediately with a
        # distinct error type so the caller can render an actionable message.
        # This catches the common "user has only Anthropic / Ollama" case
        # before we burn time iterating a loop that can't possibly succeed.
        eligible = [
            p for p in providers
            if AUDIO_CAPABLE_PROVIDERS.get(p.get("provider", ""), False)
            and p.get("api_key")
        ]
        if not eligible:
            configured_types = sorted({
                p.get("provider", "unknown") for p in providers if p.get("api_key")
            })
            audio_types = sorted(
                k for k, v in AUDIO_CAPABLE_PROVIDERS.items() if v
            )
            log.warning(
                "cloud_transcribe_no_audio_provider",
                configured_providers=configured_types,
                audio_capable_providers=audio_types,
            )
            raise NoAudioProviderError(
                "No cloud provider configured that supports audio transcription. "
                f"Configured providers: {configured_types or 'none'}. "
                f"Audio-capable provider types: {audio_types}. "
                "Add an OpenAI or Gemini API key in Settings → AI Providers, "
                "or rely on local Whisper (check GPU/CPU availability)."
            )

        last_error = None
        for provider in eligible:
            provider_type = provider.get("provider", "")
            try:
                if provider_type == "openai":
                    result = await cls._transcribe_openai(audio_path, provider, language)
                elif provider_type == "gemini":
                    result = await cls._transcribe_gemini(audio_path, provider, language)
                else:
                    continue
                _cloud_error_monitor.record_success()
                return result
            except Exception as e:
                _cloud_error_monitor.record_error(str(e))
                log.warning(
                    "cloud_transcribe_provider_failed",
                    provider=provider_type,
                    error=str(e),
                )
                last_error = e
                continue

        # All eligible providers tried and failed (API errors, rate limits, etc).
        # The pre-flight above guarantees eligible is non-empty here, so this
        # is always a real failure — not a "never had a chance" situation.
        tried = [p.get("provider") for p in eligible]
        raise RuntimeError(
            f"All audio-capable cloud providers failed. "
            f"Tried: {tried}. Last error: {last_error!r}"
        )

    @staticmethod
    async def _transcribe_openai(
        audio_path: Path,
        provider: dict,
        language: str | None,
    ) -> TranscriptionResult:
        """
        Transcribe via OpenAI Whisper API.
        Endpoint: POST /v1/audio/transcriptions
        """
        from core.crypto import decrypt_value

        api_key = decrypt_value(provider["api_key"])
        base_url = provider.get("api_base_url") or "https://api.openai.com/v1"
        url = f"{base_url}/audio/transcriptions"

        async with httpx.AsyncClient(timeout=300) as client:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, "audio/wav")}
                data = {
                    "model": "whisper-1",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                }
                if language and language != "auto":
                    data["language"] = language

                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                result = resp.json()

        segments = []
        for i, seg in enumerate(result.get("segments", [])):
            segments.append(
                TranscriptionSegment(
                    index=i,
                    start_seconds=seg["start"],
                    end_seconds=seg["end"],
                    text=seg["text"].strip(),
                    confidence=seg.get("avg_logprob"),
                )
            )

        full_text = result.get("text", "")
        return TranscriptionResult(
            segments=segments,
            language=result.get("language"),
            duration_seconds=result.get("duration"),
            engine="whisper_cloud_openai",
            model_name="whisper-1",
            word_count=len(full_text.split()) if full_text else 0,
            raw_text=full_text,
        )

    @staticmethod
    async def _transcribe_gemini(
        audio_path: Path,
        provider: dict,
        language: str | None,
    ) -> TranscriptionResult:
        """
        Transcribe via Gemini API with inline audio.
        Uses the generative model with audio file input.
        """
        from core.crypto import decrypt_value

        api_key = decrypt_value(provider["api_key"])
        model = provider.get("model", "gemini-1.5-flash")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent"
        )

        audio_bytes = audio_path.read_bytes()
        audio_b64 = base64.b64encode(audio_bytes).decode()

        prompt = (
            "Transcribe this audio file. Return a JSON array of segments, "
            "each with 'start' (seconds), 'end' (seconds), and 'text' fields. "
            "Only return the JSON array, no other text."
        )
        if language and language != "auto":
            prompt += f" The audio is in {language}."

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": audio_b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.0},
        }

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, params={"key": api_key}, json=payload)
            resp.raise_for_status()
            result = resp.json()

        # Parse Gemini's response — it returns text that should be JSON
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]

        raw_segments = json.loads(text)

        segments = []
        full_text_parts = []
        for i, seg in enumerate(raw_segments):
            segments.append(
                TranscriptionSegment(
                    index=i,
                    start_seconds=float(seg["start"]),
                    end_seconds=float(seg["end"]),
                    text=seg["text"].strip(),
                )
            )
            full_text_parts.append(seg["text"].strip())

        full_text = " ".join(full_text_parts)
        return TranscriptionResult(
            segments=segments,
            language=language,
            engine="whisper_cloud_gemini",
            model_name=model,
            word_count=len(full_text.split()) if full_text else 0,
            raw_text=full_text,
        )
