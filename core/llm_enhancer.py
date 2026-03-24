"""
LLM enhancement tasks — optional passes that improve conversion quality.

All methods are safe to call unconditionally. If no LLM client is configured,
or if the call fails, conversion succeeds without enhancement.
"""

import structlog

from core.llm_client import LLMClient, LLMRequest, LLMResponse

log = structlog.get_logger(__name__)


class LLMEnhancer:
    """Enhancement tasks using the active LLM provider."""

    def __init__(self, client: LLMClient | None):
        self.client = client

    async def correct_ocr_text(self, raw_text: str, context: str = "") -> str:
        """
        Given raw OCR output (possibly garbled), return corrected text.
        Returns raw_text unchanged if no client configured or call fails.
        """
        if not self.client or not raw_text.strip():
            return raw_text

        try:
            ctx_hint = f"\nDocument context: {context}" if context else ""
            resp = await self.client.complete(LLMRequest(
                system_prompt=(
                    "You are correcting OCR text from a scanned document. Fix spelling errors, "
                    "garbled words, and formatting artifacts caused by OCR. Preserve all content, "
                    "formatting markers (** for bold, # for headings), and line breaks. "
                    "Return only the corrected text with no explanation."
                ),
                user_message=f"Correct this OCR text:{ctx_hint}\n\n{raw_text}",
                max_tokens=min(len(raw_text) * 2, 4000),
                temperature=0.1,
            ))
            if resp.success and resp.text.strip():
                log.info("llm_ocr_correction", provider=resp.provider, tokens=resp.tokens_used)
                return resp.text.strip()
            return raw_text
        except Exception as exc:
            log.warning("llm_ocr_correction_failed", error=str(exc))
            return raw_text

    async def summarize_document(self, markdown_text: str, title: str = "") -> str | None:
        """
        Generate a 2-3 sentence plain-text summary.
        Returns None if no client or call fails.
        """
        if not self.client or not markdown_text.strip():
            return None

        try:
            title_hint = f" titled '{title}'" if title else ""
            # Truncate to ~8000 chars to keep token usage reasonable
            truncated = markdown_text[:8000]
            resp = await self.client.complete(LLMRequest(
                system_prompt=(
                    "Summarize the following document in 2-3 concise sentences. "
                    "Return only the summary text, no labels or prefixes."
                ),
                user_message=f"Document{title_hint}:\n\n{truncated}",
                max_tokens=200,
                temperature=0.3,
            ))
            if resp.success and resp.text.strip():
                log.info("llm_summary_generated", provider=resp.provider, tokens=resp.tokens_used)
                return resp.text.strip()
            return None
        except Exception as exc:
            log.warning("llm_summary_failed", error=str(exc))
            return None

    async def infer_headings(self, text_blocks: list[str]) -> list[str]:
        """
        Given a list of text blocks from a PDF with no font data,
        return the same list with heading markers added where appropriate.
        Returns input unchanged if no client or call fails.
        """
        if not self.client or not text_blocks:
            return text_blocks

        try:
            numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(text_blocks[:100]))
            resp = await self.client.complete(LLMRequest(
                system_prompt=(
                    "You are analyzing a document's structure. Each line is a text block "
                    "prefixed with [index]. Identify which blocks should be headings and "
                    "at what level (H1-H4). Return ONLY the indices that should be headings "
                    "in the format: index:level (e.g., 0:1, 5:2, 12:3). "
                    "One per line, nothing else."
                ),
                user_message=numbered,
                max_tokens=500,
                temperature=0.2,
            ))
            if not resp.success or not resp.text.strip():
                return text_blocks

            # Parse heading assignments
            heading_map: dict[int, int] = {}
            for line in resp.text.strip().splitlines():
                line = line.strip().strip(",")
                if ":" in line:
                    parts = line.split(":")
                    try:
                        idx = int(parts[0].strip())
                        level = int(parts[1].strip())
                        if 0 <= idx < len(text_blocks) and 1 <= level <= 4:
                            heading_map[idx] = level
                    except (ValueError, IndexError):
                        continue

            # Apply headings
            result = []
            for i, block in enumerate(text_blocks):
                if i in heading_map:
                    prefix = "#" * heading_map[i] + " "
                    result.append(prefix + block)
                else:
                    result.append(block)

            log.info("llm_heading_inference", headings_inferred=len(heading_map))
            return result
        except Exception as exc:
            log.warning("llm_heading_inference_failed", error=str(exc))
            return text_blocks

    async def describe_image(self, image_data: bytes, context: str = "") -> str | None:
        """
        Generate alt-text for an image. Only works with providers that support vision.
        Returns None if client is None, model lacks vision, or call fails.
        """
        if not self.client:
            return None

        # Only Anthropic and OpenAI support vision reliably
        if self.client.provider not in ("anthropic", "openai"):
            return None

        # Vision support would require base64 image encoding — implement
        # when Level 3 Adobe enrichment is needed. For now, return None.
        log.debug("llm_describe_image_stub", provider=self.client.provider)
        return None


async def get_enhancer() -> LLMEnhancer:
    """Get an LLMEnhancer using the currently active provider, or a no-op enhancer."""
    try:
        from core.database import get_active_provider
        provider_config = await get_active_provider()
        if provider_config:
            client = LLMClient(provider_config)
            return LLMEnhancer(client)
    except Exception as exc:
        log.warning("get_enhancer_failed", error=str(exc))
    return LLMEnhancer(None)
