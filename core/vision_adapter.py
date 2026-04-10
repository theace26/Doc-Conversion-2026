"""
Vision adapter — adds image/vision capability to the existing LLM provider system.

Uses the ACTIVE provider config (same shape as llm_client.py). Callers obtain the
config via database.get_active_provider(). Supported for vision: anthropic, openai,
gemini, ollama. Unsupported: custom (unknown API shape for image input).

Per Conflict Analysis: this single file replaces the entire core/vision_providers/
package. Vision uses whatever provider is already active in the LLM provider system.
"""

import base64
import io
from dataclasses import dataclass
from pathlib import Path

import mimetypes

import httpx
import structlog

log = structlog.get_logger(__name__)

_VISION_PROVIDERS = {"anthropic", "openai", "gemini", "ollama"}
_TIMEOUT = 60.0

# Anthropic API hard limit is 32 MB per request. Stay well under to leave room
# for JSON envelope, headers, and the prompt text.
_ANTHROPIC_MAX_PAYLOAD_BYTES = 24 * 1024 * 1024  # 24 MB

# Anthropic's per-image hard limit is 5 MB *encoded* (base64). Base64 inflates
# raw bytes by ~33%, so the raw budget is ~3.75 MB. We target 3.5 MB raw with a
# safety margin and use Anthropic's recommended 1568px max edge for vision.
# Pre-v0.22.18 this was unenforced and caused 154 describe_batch_failed/day
# with the same root error: "image exceeds 5 MB maximum".
_ANTHROPIC_MAX_IMAGE_RAW_BYTES = 3_500_000  # 3.5 MB raw → ~4.7 MB base64
_VISION_MAX_EDGE_PX = 1568

_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF89a", "image/gif"),
    (b"GIF87a", "image/gif"),
    (b"BM", "image/bmp"),
]


def detect_mime(file_path: Path | str) -> str:
    """Detect actual MIME from file magic bytes, fall back to extension."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return "image/webp"
        for magic, mime in _MAGIC_BYTES:
            if header[: len(magic)] == magic:
                return mime
    except OSError:
        pass
    return mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"


_PROVIDER_LIMITS = {
    "anthropic": {
        "max_request_bytes": 24 * 1024 * 1024,
        "max_image_raw_bytes": 3_500_000,
        "max_images_per_batch": 20,
        "max_edge_px": 1568,
    },
    "openai": {
        "max_request_bytes": 18 * 1024 * 1024,
        "max_image_raw_bytes": 18 * 1024 * 1024,
        "max_images_per_batch": 10,
        "max_edge_px": 2048,
    },
    "gemini": {
        "max_request_bytes": 18 * 1024 * 1024,
        "max_image_raw_bytes": 18 * 1024 * 1024,
        "max_images_per_batch": 16,
        "max_edge_px": 3072,
    },
    "ollama": {
        "max_request_bytes": 50 * 1024 * 1024,
        "max_image_raw_bytes": 50 * 1024 * 1024,
        "max_images_per_batch": 5,
        "max_edge_px": 1568,
    },
}
_DEFAULT_LIMITS = _PROVIDER_LIMITS["anthropic"]


def get_provider_limits(provider: str) -> dict:
    """Return batch limits for the given provider."""
    return _PROVIDER_LIMITS.get(provider, _DEFAULT_LIMITS)


def plan_batches(
    images: list[tuple[Path, int]],
    provider: str,
) -> list[list[Path]]:
    """Bin-pack images into batches sized per provider limits."""
    limits = get_provider_limits(provider)
    max_bytes = limits["max_request_bytes"]
    max_count = limits["max_images_per_batch"]

    batches: list[list[Path]] = []
    current_batch: list[Path] = []
    current_bytes = 0

    for path, size in images:
        encoded_size = int(size * 1.34)
        if current_batch and (
            current_bytes + encoded_size > max_bytes
            or len(current_batch) >= max_count
        ):
            batches.append(current_batch)
            current_batch = []
            current_bytes = 0
        current_batch.append(path)
        current_bytes += encoded_size

    if current_batch:
        batches.append(current_batch)

    return batches


def _compress_image_for_vision(
    raw: bytes, mime_or_suffix: str
) -> tuple[bytes, str]:
    """
    Ensure an image fits within the per-image vision API budget.

    Returns (possibly-recompressed bytes, mime type). Strategy:
      1. If already under the raw byte budget, return unchanged.
      2. Otherwise downscale longest edge to ``_VISION_MAX_EDGE_PX`` and
         re-encode as JPEG quality 85. JPEG q85 + 1568px is Anthropic's
         own vision recommendation and gives 200-800 KB typical output.
      3. If JPEG encoding fails (e.g. transparent PNG with alpha), fall
         back to PNG re-encode at the smaller resolution.

    Pillow is already a dep (used by EPS/raster handlers). On any failure
    the original bytes are returned so the caller's existing 5 MB error
    path still fires — this function never raises.
    """
    if mime_or_suffix.startswith("image/"):
        mime = mime_or_suffix
    else:
        mime = mimetypes.guess_type(f"file{mime_or_suffix}")[0] or "image/png"

    if len(raw) <= _ANTHROPIC_MAX_IMAGE_RAW_BYTES:
        return raw, mime

    try:
        from PIL import Image  # local import — heavy module, only load on need

        img = Image.open(io.BytesIO(raw))
        img.load()
        # Convert palette / alpha modes to RGB for JPEG encode
        if img.mode in ("P", "RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Longest-edge downscale
        w, h = img.size
        longest = max(w, h)
        if longest > _VISION_MAX_EDGE_PX:
            scale = _VISION_MAX_EDGE_PX / longest
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        compressed = out.getvalue()

        # If still over budget (very rare for 1568px JPEG), drop quality
        if len(compressed) > _ANTHROPIC_MAX_IMAGE_RAW_BYTES:
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=70, optimize=True)
            compressed = out.getvalue()

        log.info(
            "vision_adapter.image_recompressed",
            original_bytes=len(raw),
            new_bytes=len(compressed),
            new_size=img.size,
        )
        return compressed, "image/jpeg"
    except Exception as exc:
        log.warning(
            "vision_adapter.image_compress_failed",
            error=str(exc),
            original_bytes=len(raw),
        )
        # Return original; the API call will surface the real 5 MB error
        return raw, mime


@dataclass
class FrameDescription:
    scene_index: int
    description: str
    provider_id: str
    model: str
    error: str | None = None


@dataclass
class BatchImageResult:
    index: int
    description: str
    extracted_text: str
    error: str | None = None
    tokens_used: int | None = None


class VisionAdapter:
    """
    Adds image/vision capability to the existing LLM provider system.

    Takes the ACTIVE provider config dict (same shape as what llm_client.py
    uses internally -- already decrypted, already validated by llm_providers.py).
    """

    def __init__(self, provider_config: dict):
        self._provider = provider_config.get("provider", "")
        self._api_key = provider_config.get("api_key", "")
        self._model = provider_config.get("model", "")
        self._base_url = provider_config.get("api_base_url", "")

    def supports_vision(self) -> bool:
        return self._provider in _VISION_PROVIDERS

    async def describe_frame(
        self, image_path: Path, prompt: str, scene_index: int
    ) -> FrameDescription:
        """
        Describe a single image frame. MUST NEVER RAISE.
        All exceptions caught, FrameDescription.error set on failure.
        """
        if not self.supports_vision():
            return FrameDescription(
                scene_index=scene_index,
                description="",
                provider_id=self._provider,
                model=self._model,
                error=f"[vision unavailable -- {self._provider} does not support image input]",
            )
        try:
            raw = image_path.read_bytes()
            # Apply per-image budget for ALL providers — the heaviest cap
            # (Anthropic's 5 MB) is also a sensible default elsewhere and
            # keeps token usage / latency in check.
            raw, mime = _compress_image_for_vision(raw, image_path.suffix)
            image_b64 = base64.b64encode(raw).decode()

            if self._provider == "anthropic":
                return await self._describe_anthropic(image_b64, mime, prompt, scene_index)
            elif self._provider == "openai":
                return await self._describe_openai(image_b64, mime, prompt, scene_index)
            elif self._provider == "gemini":
                return await self._describe_gemini(image_b64, mime, prompt, scene_index)
            elif self._provider == "ollama":
                return await self._describe_ollama(image_b64, prompt, scene_index)
            else:
                return FrameDescription(
                    scene_index=scene_index,
                    description="",
                    provider_id=self._provider,
                    model=self._model,
                    error=f"[vision unavailable -- unknown provider {self._provider}]",
                )
        except Exception as e:
            log.error(
                "vision_adapter.describe_frame_failed",
                provider=self._provider,
                scene=scene_index,
                error=str(e),
            )
            return FrameDescription(
                scene_index=scene_index,
                description="",
                provider_id=self._provider,
                model=self._model,
                error=f"[vision unavailable -- {e.__class__.__name__}: {e}]",
            )

    async def describe_batch(
        self, image_paths: list[Path], prompt: str | None = None
    ) -> list["BatchImageResult"]:
        """
        Describe multiple images in a single API call.
        Returns one BatchImageResult per input path, in input order.
        Never raises — all exceptions captured in BatchImageResult.error.
        """
        if not image_paths:
            return []

        if not self.supports_vision():
            return [
                BatchImageResult(
                    index=i, description="", extracted_text="",
                    error=f"[vision unavailable -- {self._provider} does not support image input]",
                )
                for i in range(len(image_paths))
            ]

        if prompt is None:
            prompt = (
                "For each image provided (in order), return a JSON array where each element has:\n"
                "  'description': a factual description of the image content (objects, people, "
                "scenes, charts, diagrams, any visible text). Be concise.\n"
                "  'extracted_text': any legible text found in the image verbatim. "
                "Empty string if none.\n"
                "Return ONLY the JSON array with no prose before or after."
            )

        try:
            if self._provider == "anthropic":
                return await self._batch_anthropic(image_paths, prompt)
            elif self._provider == "openai":
                return await self._batch_openai(image_paths, prompt)
            elif self._provider == "gemini":
                return await self._batch_gemini(image_paths, prompt)
            elif self._provider == "ollama":
                return await self._batch_ollama(image_paths, prompt)
            else:
                return [
                    BatchImageResult(
                        index=i, description="", extracted_text="",
                        error=f"[vision unavailable -- unknown provider {self._provider}]",
                    )
                    for i in range(len(image_paths))
                ]
        except Exception as exc:
            # v0.22.14: capture HTTP response body when present so 400/etc
            # carry the actual provider error reason ("Image too large",
            # "Invalid base64", etc) instead of the generic
            # "Client error '400 Bad Request' for url ...". The previous
            # generic message hid the real cause and was the main reason
            # the analysis_queue had 1,150 unexplained failures.
            response_body = ""
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    response_body = response.text[:500]
                except Exception:
                    pass

            log.error(
                "vision_adapter.describe_batch_failed",
                provider=self._provider,
                count=len(image_paths),
                error=str(exc),
                exc_type=type(exc).__name__,
                response_body=response_body,
                first_image=str(image_paths[0]) if image_paths else None,
            )
            err_for_rows = str(exc)
            if response_body:
                err_for_rows = f"{err_for_rows} | body: {response_body}"
            return [
                BatchImageResult(index=i, description="", extracted_text="", error=err_for_rows)
                for i in range(len(image_paths))
            ]

    def _parse_batch_response(self, text: str, count: int) -> list[dict]:
        """Parse JSON array from LLM response. Extracts from prose if needed."""
        import json
        import re

        text = text.strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        log.warning(
            "vision_adapter.batch_parse_failed",
            provider=self._provider,
            response_preview=text[:200],
        )
        return [
            {"description": "", "extracted_text": "", "error": "failed to parse LLM response"}
            for _ in range(count)
        ]

    async def _batch_anthropic(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        # Pre-encode all images and group into sub-batches that stay under
        # Anthropic's 32 MB request limit. Each sub-batch hits the API once.
        encoded: list[tuple[Path, str, str, int]] = []  # (path, b64, mime, size)
        for path in image_paths:
            try:
                raw = path.read_bytes()
            except OSError as exc:
                log.warning("vision_adapter.image_read_failed", path=str(path), error=str(exc))
                encoded.append((path, "", "", 0))
                continue
            # Per-image cap enforcement (Anthropic 5 MB hard limit). Compresses
            # only oversized images; small images pass through untouched.
            raw, mime = _compress_image_for_vision(raw, path.suffix)
            b64 = base64.b64encode(raw).decode()
            encoded.append((path, b64, mime, len(b64)))

        # Greedy split into size-bounded sub-batches (preserve original index order).
        sub_batches: list[list[int]] = []
        current: list[int] = []
        current_size = 0
        for idx, (_, b64, _, size) in enumerate(encoded):
            if not b64:
                # Failed to read; place into its own slot so the index is preserved
                if current:
                    sub_batches.append(current)
                    current, current_size = [], 0
                sub_batches.append([idx])
                continue
            if current and current_size + size > _ANTHROPIC_MAX_PAYLOAD_BYTES:
                sub_batches.append(current)
                current, current_size = [], 0
            current.append(idx)
            current_size += size
        if current:
            sub_batches.append(current)

        # Per-image results, populated in original order.
        results: list[BatchImageResult | None] = [None] * len(image_paths)

        base = self._base_url or "https://api.anthropic.com"
        async with httpx.AsyncClient(timeout=_TIMEOUT * 4) as client:
            for batch_indices in sub_batches:
                # Skip slots that failed to read (single-index batches with empty b64).
                if len(batch_indices) == 1 and not encoded[batch_indices[0]][1]:
                    i = batch_indices[0]
                    results[i] = BatchImageResult(
                        index=i, description="", extracted_text="",
                        error="[image read failed]",
                    )
                    continue

                content: list[dict] = []
                for i in batch_indices:
                    _, b64, mime, _ = encoded[i]
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64},
                    })
                content.append({"type": "text", "text": prompt})

                resp = await client.post(
                    f"{base}/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "max_tokens": 400 * len(batch_indices),
                        "messages": [{"role": "user", "content": content}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = "".join(
                    block.get("text", "")
                    for block in data.get("content", [])
                    if block.get("type") == "text"
                )
                usage = data.get("usage", {})
                tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)

                parsed = self._parse_batch_response(text, len(batch_indices))
                per_image = (tokens // len(batch_indices)) if tokens else None
                for slot, item in zip(batch_indices, parsed):
                    results[slot] = BatchImageResult(
                        index=slot,
                        description=item.get("description", ""),
                        extracted_text=item.get("extracted_text", ""),
                        error=item.get("error"),
                        tokens_used=per_image,
                    )

        # Fill any remaining None slots (defensive — shouldn't happen).
        for i, r in enumerate(results):
            if r is None:
                results[i] = BatchImageResult(
                    index=i, description="", extracted_text="",
                    error="[no result returned]",
                )
        return results  # type: ignore[return-value]

    async def _batch_openai(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for path in image_paths:
            raw = path.read_bytes()
            raw, mime = _compress_image_for_vision(raw, path.suffix)
            image_b64 = base64.b64encode(raw).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}", "detail": "low"},
            })

        timeout = max(_TIMEOUT, _TIMEOUT * len(image_paths) / 3)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": self._model or "gpt-4o",
                    "max_tokens": 400 * len(image_paths),
                    "messages": [{"role": "user", "content": content}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens") or 0

        parsed = self._parse_batch_response(text, len(image_paths))
        per_image = (tokens // len(image_paths)) if tokens and len(image_paths) > 0 else None
        return [
            BatchImageResult(
                index=i,
                description=item.get("description", ""),
                extracted_text=item.get("extracted_text", ""),
                error=item.get("error"),
                tokens_used=per_image,
            )
            for i, item in enumerate(parsed)
        ]

    async def _batch_gemini(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        base = self._base_url or "https://generativelanguage.googleapis.com"
        parts: list[dict] = [{"text": prompt}]
        for path in image_paths:
            raw = path.read_bytes()
            raw, mime = _compress_image_for_vision(raw, path.suffix)
            image_b64 = base64.b64encode(raw).decode()
            parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})

        timeout = max(_TIMEOUT, _TIMEOUT * len(image_paths) / 3)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/v1beta/models/{self._model}:generateContent",
                params={"key": self._api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"maxOutputTokens": 400 * len(image_paths)},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                part.get("text", "")
                for candidate in data.get("candidates", [])
                for part in candidate.get("content", {}).get("parts", [])
            )
            usage_meta = data.get("usageMetadata", {})
            tokens = (usage_meta.get("promptTokenCount", 0) or 0) + (usage_meta.get("candidatesTokenCount", 0) or 0)

        parsed = self._parse_batch_response(text, len(image_paths))
        per_image = (tokens // len(image_paths)) if tokens and len(image_paths) > 0 else None
        return [
            BatchImageResult(
                index=i,
                description=item.get("description", ""),
                extracted_text=item.get("extracted_text", ""),
                error=item.get("error"),
                tokens_used=per_image,
            )
            for i, item in enumerate(parsed)
        ]

    async def _batch_ollama(self, image_paths: list[Path], prompt: str) -> list["BatchImageResult"]:
        """Try multi-image batch; fall back to sequential describe_frame() calls if model rejects it."""
        base = self._base_url or "http://localhost:11434"
        images_b64 = [base64.b64encode(p.read_bytes()).decode() for p in image_paths]

        try:
            async with httpx.AsyncClient(timeout=120.0 * len(image_paths)) as client:
                resp = await client.post(
                    f"{base}/api/generate",
                    json={
                        "model": self._model or "llava",
                        "prompt": prompt,
                        "images": images_b64,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                text = resp.json().get("response", "").strip()

            parsed = self._parse_batch_response(text, len(image_paths))
            results = [
                BatchImageResult(
                    index=i,
                    description=item.get("description", ""),
                    extracted_text=item.get("extracted_text", ""),
                    error=item.get("error"),
                )
                for i, item in enumerate(parsed)
            ]
            if all(r.error for r in results):
                raise ValueError("all results failed — falling back to sequential")
            return results

        except Exception:
            log.info("vision_adapter.ollama_batch_fallback_sequential", count=len(image_paths))
            out = []
            for i, path in enumerate(image_paths):
                fd = await self.describe_frame(path, prompt, scene_index=i)
                out.append(BatchImageResult(
                    index=i,
                    description=fd.description,
                    extracted_text="",
                    error=fd.error,
                ))
            return out

    async def health_check(self) -> tuple[bool, str]:
        """Fast connectivity check (5s timeout). Never raises."""
        try:
            if self._provider == "ollama":
                base = self._base_url or "http://localhost:11434"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{base}/api/tags")
                    if resp.status_code != 200:
                        return False, f"Ollama returned {resp.status_code}"
                    models = [
                        m.get("name", "").split(":")[0]
                        for m in resp.json().get("models", [])
                    ]
                    if self._model and self._model not in models:
                        return True, f"Ollama reachable -- {self._model} not installed"
                    return True, f"Ollama -- {self._model} available"

            elif self._provider == "openai":
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                    if resp.status_code == 401:
                        return False, "Invalid API key"
                    if resp.status_code == 429:
                        return True, "OpenAI reachable (rate limited)"
                    return True, "OpenAI API reachable"

            elif self._provider == "anthropic":
                base = self._base_url or "https://api.anthropic.com"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{base}/v1/messages",
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "max_tokens": 5,
                            "messages": [{"role": "user", "content": "Test"}],
                        },
                    )
                    if resp.status_code == 401:
                        return False, "Invalid API key"
                    if resp.status_code == 429:
                        return True, "Anthropic reachable (rate limited)"
                    return True, "Anthropic API reachable"

            elif self._provider == "gemini":
                base = self._base_url or "https://generativelanguage.googleapis.com"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{base}/v1beta/models/{self._model}:generateContent",
                        params={"key": self._api_key},
                        json={"contents": [{"parts": [{"text": "Test"}]}]},
                    )
                    if resp.status_code in (400, 403):
                        return False, "Invalid API key"
                    return True, "Gemini API reachable"

            return False, f"Unknown provider: {self._provider}"
        except httpx.ConnectError:
            return False, f"{self._provider} unreachable"
        except Exception as e:
            return False, str(e)

    # ── Provider-specific implementations ─────────────────────────────────────

    async def _describe_anthropic(
        self, image_b64: str, mime: str, prompt: str, scene_index: int
    ) -> FrameDescription:
        base = self._base_url or "https://api.anthropic.com"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 300,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": image_b64,
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            return FrameDescription(
                scene_index=scene_index,
                description=text.strip(),
                provider_id="anthropic",
                model=self._model,
            )

    async def _describe_openai(
        self, image_b64: str, mime: str, prompt: str, scene_index: int
    ) -> FrameDescription:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model or "gpt-4o",
                    "max_tokens": 300,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,{image_b64}",
                                        "detail": "low",
                                    },
                                },
                            ],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return FrameDescription(
                scene_index=scene_index,
                description=text.strip(),
                provider_id="openai",
                model=self._model,
            )

    async def _describe_gemini(
        self, image_b64: str, mime: str, prompt: str, scene_index: int
    ) -> FrameDescription:
        base = self._base_url or "https://generativelanguage.googleapis.com"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/v1beta/models/{self._model}:generateContent",
                params={"key": self._api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inline_data": {
                                        "mime_type": mime,
                                        "data": image_b64,
                                    }
                                },
                            ]
                        }
                    ],
                    "generationConfig": {"maxOutputTokens": 300},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = ""
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    text += part.get("text", "")
            return FrameDescription(
                scene_index=scene_index,
                description=text.strip(),
                provider_id="gemini",
                model=self._model,
            )

    async def _describe_ollama(
        self, image_b64: str, prompt: str, scene_index: int
    ) -> FrameDescription:
        base = self._base_url or "http://localhost:11434"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base}/api/generate",
                json={
                    "model": self._model or "llava",
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return FrameDescription(
                scene_index=scene_index,
                description=data.get("response", "").strip(),
                provider_id="ollama",
                model=self._model,
            )
