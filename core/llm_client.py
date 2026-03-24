"""
Unified async LLM client that normalizes calls across providers.

All providers receive the same input (LLMRequest) and return the same
output shape (LLMResponse). This is the only file that knows about
provider-specific API differences.
"""

import time
from dataclasses import dataclass, field

import httpx
import structlog

log = structlog.get_logger(__name__)


@dataclass
class LLMRequest:
    system_prompt: str
    user_message: str
    max_tokens: int = 1000
    temperature: float = 0.2


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    tokens_used: int | None = None
    duration_ms: int = 0
    success: bool = True
    error: str | None = None


class LLMClient:
    """Routes LLM calls to the correct provider implementation."""

    def __init__(self, provider_config: dict):
        self.provider = provider_config.get("provider", "")
        self.model = provider_config.get("model", "")
        self.api_key = provider_config.get("api_key", "")
        self.api_base_url = provider_config.get("api_base_url", "")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route to the correct provider implementation."""
        t_start = time.perf_counter()
        try:
            if self.provider == "anthropic":
                resp = await self._complete_anthropic(request)
            elif self.provider == "openai":
                resp = await self._complete_openai(request)
            elif self.provider == "gemini":
                resp = await self._complete_gemini(request)
            elif self.provider == "ollama":
                resp = await self._complete_ollama(request)
            elif self.provider == "custom":
                resp = await self._complete_custom(request)
            else:
                return LLMResponse(
                    text="", provider=self.provider, model=self.model,
                    success=False, error=f"Unknown provider: {self.provider}",
                )
            resp.duration_ms = int((time.perf_counter() - t_start) * 1000)
            return resp
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t_start) * 1000)
            log.warning("llm_call_failed", provider=self.provider, error=str(exc))
            return LLMResponse(
                text="", provider=self.provider, model=self.model,
                duration_ms=duration_ms, success=False, error=str(exc),
            )

    async def ping(self) -> tuple[bool, str]:
        """
        Verify the provider is reachable and the API key works.
        Returns (success, message). Never raises.
        """
        try:
            request = LLMRequest(
                system_prompt="Reply with the word OK.",
                user_message="Test",
                max_tokens=5,
                temperature=0.0,
            )

            # Ollama: just check if server is up and model exists
            if self.provider == "ollama":
                return await self._ping_ollama()

            resp = await self.complete(request)
            if resp.success:
                return True, f"{self.model} responded in {resp.duration_ms}ms"
            return False, resp.error or "Unknown error"
        except Exception as exc:
            return False, str(exc)

    async def _ping_ollama(self) -> tuple[bool, str]:
        """Check Ollama server is up and model is available."""
        base = self.api_base_url or "http://localhost:11434"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/api/tags")
                if resp.status_code != 200:
                    return False, f"Ollama returned {resp.status_code}"
                data = resp.json()
                models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
                if self.model and self.model not in models:
                    return False, f"Model '{self.model}' not found. Available: {', '.join(models)}"
                return True, f"Ollama running, {len(models)} models available"
        except httpx.ConnectError:
            return False, f"Cannot connect to Ollama at {base} — is it running?"
        except Exception as exc:
            return False, str(exc)

    async def _complete_anthropic(self, request: LLMRequest) -> LLMResponse:
        base = self.api_base_url or "https://api.anthropic.com"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "system": request.system_prompt,
                    "messages": [{"role": "user", "content": request.user_message}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            usage = data.get("usage", {})
            tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            return LLMResponse(
                text=text, provider="anthropic", model=self.model,
                tokens_used=tokens, success=True,
            )

    async def _complete_openai(self, request: LLMRequest) -> LLMResponse:
        base = self.api_base_url or "https://api.openai.com"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_message},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens")
            return LLMResponse(
                text=text, provider="openai", model=self.model,
                tokens_used=tokens, success=True,
            )

    async def _complete_gemini(self, request: LLMRequest) -> LLMResponse:
        base = self.api_base_url or "https://generativelanguage.googleapis.com"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/v1beta/models/{self.model}:generateContent",
                params={"key": self.api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": request.system_prompt}]},
                    "contents": [{"parts": [{"text": request.user_message}]}],
                    "generationConfig": {
                        "maxOutputTokens": request.max_tokens,
                        "temperature": request.temperature,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = ""
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    text += part.get("text", "")
            usage_meta = data.get("usageMetadata", {})
            tokens = (usage_meta.get("promptTokenCount", 0) or 0) + (usage_meta.get("candidatesTokenCount", 0) or 0)
            return LLMResponse(
                text=text, provider="gemini", model=self.model,
                tokens_used=tokens, success=True,
            )

    async def _complete_ollama(self, request: LLMRequest) -> LLMResponse:
        base = self.api_base_url or "http://localhost:11434"
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Try OpenAI-compatible endpoint first
            try:
                resp = await client.post(
                    f"{base}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "max_tokens": request.max_tokens,
                        "temperature": request.temperature,
                        "messages": [
                            {"role": "system", "content": request.system_prompt},
                            {"role": "user", "content": request.user_message},
                        ],
                    },
                )
                if resp.status_code != 404:
                    resp.raise_for_status()
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    return LLMResponse(
                        text=text, provider="ollama", model=self.model, success=True,
                    )
            except httpx.HTTPStatusError:
                pass  # fallback to native API

            # Fallback: native /api/generate
            resp = await client.post(
                f"{base}/api/generate",
                json={
                    "model": self.model,
                    "system": request.system_prompt,
                    "prompt": request.user_message,
                    "stream": False,
                    "options": {
                        "temperature": request.temperature,
                        "num_predict": request.max_tokens,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                text=data.get("response", ""),
                provider="ollama",
                model=self.model,
                success=True,
            )

    async def _complete_custom(self, request: LLMRequest) -> LLMResponse:
        """Custom provider assumes OpenAI-compatible API."""
        if not self.api_base_url:
            return LLMResponse(
                text="", provider="custom", model=self.model,
                success=False, error="No base URL configured for custom provider",
            )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.api_base_url}/v1/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_message},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return LLMResponse(
                text=text, provider="custom", model=self.model, success=True,
            )
