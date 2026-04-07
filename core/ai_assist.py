"""
AI-assisted search synthesis using the Anthropic Messages API.
Streams a grounded answer based on Meilisearch result snippets.

Provider key resolution (v0.22.10)
----------------------------------
The API key, model, and base URL are pulled from the **active llm_providers
record** managed via the Settings → Providers page — the same source the
image scanner / vision pipeline uses. The legacy `ANTHROPIC_API_KEY` env var
is honored as a fallback for backward compatibility but should be considered
deprecated.

Only an `anthropic` provider is supported by AI Assist today (because the
streaming SSE format and `x-api-key` header are Anthropic-specific). If the
active provider is OpenAI/Gemini/Ollama/etc, AI Assist returns a clear
configuration error telling the user to set Anthropic as the active provider.
"""
import os
import json
import httpx
import structlog
from typing import AsyncGenerator, Optional

log = structlog.get_logger()

ANTHROPIC_API_URL_DEFAULT = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 700
DEFAULT_MAX_SNIPPETS = 8

SYSTEM_PROMPT = """You are a document search assistant for an internal organizational \
document repository. Your job is to synthesize a concise, accurate answer to the \
user's search query using only the document snippets provided.

Rules:
- Cite sources inline using [1], [2], etc. matching the document numbers given
- Never fabricate information not present in the snippets
- If the snippets don't contain enough to answer, say so clearly and briefly
- Write in direct prose — avoid bullet lists unless the query calls for enumeration
- Keep the response under 380 words
- Do not mention that you are an AI or describe your process"""

EXPAND_SYSTEM_PROMPT = """You are a document analysis assistant. The user wants a \
thorough analysis of a specific document in context of their original search query.

Rules:
- Base your analysis entirely on the document content provided
- Highlight the sections most relevant to the query
- Identify key facts, decisions, dates, or entities if present
- Keep the response under 600 words
- Use plain prose with minimal formatting"""


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ~ 4 characters (English prose)."""
    return max(1, len(text) // 4)


async def _get_provider_config() -> dict:
    """
    Resolve the AI Assist API key + model + base URL.

    Lookup order (v0.22.11):
      1. Provider opted-in via the "Use for AI Assist" checkbox on the
         Providers page (`llm_providers.use_for_ai_assist=1`). This is the
         preferred path — admins explicitly choose which provider AI Assist
         uses, independent of the image-scanner active provider.
      2. Active llm_provider (`is_active=1`) if no provider has been opted in
         yet — backward compatibility with v0.22.10 behavior.
      3. `ANTHROPIC_API_KEY` env var if no provider record exists at all
         (legacy / dev compat, deprecated).

    Returns a dict with these keys:
        api_key          — str or None
        model            — str (resolved from provider, AI_ASSIST_MODEL env, or DEFAULT_MODEL)
        api_url          — str (the messages endpoint URL)
        provider         — str ("anthropic" / "env_fallback" / "openai" / etc.)
        provider_source  — str ("opted_in" / "active_fallback" / "env_fallback" / "none")
        configured       — bool (True if api_key is non-empty)
        compatible       — bool (True if the provider is anthropic; AI Assist
                           only supports Anthropic streaming today)
        error            — str or None (human-readable reason when not usable)
    """
    api_key: Optional[str] = None
    model = os.environ.get("AI_ASSIST_MODEL") or DEFAULT_MODEL
    api_url = ANTHROPIC_API_URL_DEFAULT
    provider_name = "env_fallback"
    provider_source = "none"
    compatible = True
    error: Optional[str] = None

    chosen: Optional[dict] = None

    # 1. Preferred: provider opted in via "Use for AI Assist" checkbox.
    try:
        from core.db.catalog import get_ai_assist_provider, get_active_provider  # local import
        opted_in = await get_ai_assist_provider()
    except Exception as exc:
        log.warning("ai_assist.provider_lookup_failed", error=str(exc))
        opted_in = None

    if opted_in and opted_in.get("api_key"):
        chosen = opted_in
        provider_source = "opted_in"
    else:
        # 2. Fallback: the image scanner's active provider.
        try:
            active = await get_active_provider()
        except Exception:
            active = None
        if active and active.get("api_key"):
            chosen = active
            provider_source = "active_fallback"

    if chosen:
        provider_name = (chosen.get("provider") or "").strip().lower()
        if provider_name == "anthropic":
            api_key = chosen["api_key"]
            if chosen.get("model"):
                model = chosen["model"]
            if chosen.get("api_base_url"):
                base = chosen["api_base_url"].rstrip("/")
                api_url = base + "/v1/messages" if not base.endswith("/v1/messages") else base
        else:
            compatible = False
            if provider_source == "opted_in":
                error = (
                    f"The provider opted in for AI Assist is '{provider_name}'. "
                    f"AI Assist currently requires an Anthropic provider. Edit the "
                    f"provider on the Providers page or opt in a different one."
                )
            else:
                error = (
                    f"Active LLM provider is '{provider_name}'. AI Assist currently "
                    f"requires an Anthropic provider. Either opt in a specific Anthropic "
                    f"provider via the 'Use for AI Assist' checkbox on the Providers page, "
                    f"or switch the active provider."
                )

    # 3. Last-resort env fallback when there is no provider record at all.
    if not api_key and chosen is None:
        env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if env_key:
            api_key = env_key
            provider_name = "env_fallback"
            provider_source = "env_fallback"

    return {
        "api_key": api_key,
        "model": model,
        "api_url": api_url,
        "provider": provider_name,
        "provider_source": provider_source,
        "configured": bool(api_key),
        "compatible": compatible,
        "error": error,
    }


def _build_snippet_prompt(query: str, results: list[dict]) -> str:
    """Build the user-turn prompt from search results."""
    snippets = results[:DEFAULT_MAX_SNIPPETS]
    lines = [f'Search query: "{query}"\n']
    lines.append(f"Top {len(snippets)} matching documents:\n")
    for i, r in enumerate(snippets, 1):
        title = r.get("title") or r.get("file_name") or "Untitled"
        file_type = r.get("file_type") or r.get("extension") or "file"
        snippet = (r.get("snippet") or r.get("_formatted", {}).get("content") or "").strip()
        lines.append(f"[{i}] {title} ({file_type})")
        lines.append(snippet[:600] if snippet else "(no preview available)")
        lines.append("")
    lines.append(
        "Synthesize a direct answer to the search query from these documents. "
        "Cite sources by number. If a source is particularly relevant, say why."
    )
    return "\n".join(lines)


async def stream_search_synthesis(
    query: str,
    results: list[dict],
    on_complete=None,
) -> AsyncGenerator[str, None]:
    """
    Stream a Claude synthesis of search results as SSE-formatted strings.
    Yields lines ready to write directly to a StreamingResponse.
    """
    cfg = await _get_provider_config()
    if not cfg["compatible"]:
        yield _sse("error", {"message": cfg["error"] or "AI Assist provider is not compatible"})
        return
    if not cfg["configured"]:
        yield _sse("error", {
            "message": "AI Assist is not configured. Add an Anthropic provider with a valid "
                       "API key on the Settings \u2192 Providers page and mark it active.",
        })
        return

    api_key = cfg["api_key"]
    model = cfg["model"]
    api_url = cfg["api_url"]
    max_tokens = int(os.environ.get("AI_ASSIST_MAX_TOKENS", DEFAULT_MAX_TOKENS))

    user_prompt = _build_snippet_prompt(query, results)
    input_tokens_est = _estimate_tokens(SYSTEM_PROMPT + user_prompt)
    output_chars = 0

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "stream": True,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    log.info("ai_assist.stream_start", query=query, result_count=len(results),
             model=model, provider=cfg["provider"])

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST", api_url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error(
                        "ai_assist.api_error",
                        status=resp.status_code,
                        body=body.decode()[:300],
                    )
                    yield _sse("error", {"message": f"Claude API error ({resp.status_code})"})
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")

                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield _sse("chunk", {"text": text})
                                output_chars += len(text)

                    elif etype == "message_stop":
                        sources = [
                            {
                                "index": i + 1,
                                "title": (r.get("title") or r.get("file_name") or "Untitled"),
                                "doc_id": r.get("id") or r.get("doc_id") or "",
                                "file_type": r.get("file_type") or r.get("extension") or "",
                                "path": r.get("path") or r.get("file_path") or "",
                            }
                            for i, r in enumerate(results[:DEFAULT_MAX_SNIPPETS])
                        ]
                        yield _sse("sources", {"sources": sources})
                        if on_complete:
                            try:
                                await on_complete(input_tokens_est, max(1, output_chars // 4))
                            except Exception as cb_exc:
                                log.error("ai_assist.callback_error", error=str(cb_exc))
                        yield _sse("done", {})
                        log.info("ai_assist.stream_complete", query=query)
                        return

    except httpx.TimeoutException:
        log.warning("ai_assist.timeout", query=query)
        yield _sse("error", {"message": "AI Assist timed out. Try again."})
    except Exception as exc:
        log.error("ai_assist.unexpected_error", error=str(exc))
        yield _sse("error", {"message": "Unexpected error during AI synthesis."})


async def stream_document_expand(
    query: str,
    doc_id: str,
    markdown_content: str,
    on_complete=None,
) -> AsyncGenerator[str, None]:
    """
    Stream a deep analysis of a single document in context of the original query.
    markdown_content should be the full converted markdown text.
    """
    cfg = await _get_provider_config()
    if not cfg["compatible"]:
        yield _sse("error", {"message": cfg["error"] or "AI Assist provider is not compatible"})
        return
    if not cfg["configured"]:
        yield _sse("error", {
            "message": "AI Assist is not configured. Add an Anthropic provider with a valid "
                       "API key on the Settings \u2192 Providers page and mark it active.",
        })
        return

    api_key = cfg["api_key"]
    model = cfg["model"]
    api_url = cfg["api_url"]
    max_tokens = int(os.environ.get("AI_ASSIST_EXPAND_MAX_TOKENS", 900))

    # Truncate content to avoid blowing context
    content_preview = markdown_content[:12000]
    if len(markdown_content) > 12000:
        content_preview += "\n\n[document truncated for analysis]"

    user_prompt = (
        f'Original search query: "{query}"\n\n'
        f"Full document content:\n\n{content_preview}\n\n"
        "Provide a thorough analysis of this document as it relates to the query."
    )
    input_tokens_est = _estimate_tokens(EXPAND_SYSTEM_PROMPT + user_prompt)
    output_chars = 0

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": EXPAND_SYSTEM_PROMPT,
        "stream": True,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    log.info("ai_assist.expand_start", query=query, doc_id=doc_id,
             model=model, provider=cfg["provider"])

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream(
                "POST", api_url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("ai_assist.expand_api_error", status=resp.status_code)
                    yield _sse("error", {"message": f"Claude API error ({resp.status_code})"})
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield _sse("chunk", {"text": text})
                                output_chars += len(text)
                    elif etype == "message_stop":
                        if on_complete:
                            try:
                                await on_complete(input_tokens_est, max(1, output_chars // 4))
                            except Exception as cb_exc:
                                log.error("ai_assist.expand_callback_error", error=str(cb_exc))
                        yield _sse("done", {})
                        log.info("ai_assist.expand_complete", doc_id=doc_id)
                        return

    except httpx.TimeoutException:
        log.warning("ai_assist.expand_timeout", doc_id=doc_id)
        yield _sse("error", {"message": "Deep analysis timed out."})
    except Exception as exc:
        log.error("ai_assist.expand_unexpected", error=str(exc))
        yield _sse("error", {"message": "Unexpected error during document analysis."})


def _sse(event_type: str, data: dict) -> str:
    """Format a single SSE line."""
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"
