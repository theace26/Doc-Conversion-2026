"""
AI-assisted search synthesis using the Anthropic Messages API.
Streams a grounded answer based on Meilisearch result snippets.
"""
import os
import json
import httpx
import structlog
from typing import AsyncGenerator

log = structlog.get_logger()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
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


def _get_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


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
    api_key = _get_api_key()
    if not api_key:
        yield _sse("error", {"message": "AI Assist is not configured (missing ANTHROPIC_API_KEY)"})
        return

    model = os.environ.get("AI_ASSIST_MODEL", DEFAULT_MODEL)
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

    log.info("ai_assist.stream_start", query=query, result_count=len(results), model=model)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST", ANTHROPIC_API_URL, json=payload, headers=headers
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
    api_key = _get_api_key()
    if not api_key:
        yield _sse("error", {"message": "AI Assist is not configured (missing ANTHROPIC_API_KEY)"})
        return

    model = os.environ.get("AI_ASSIST_MODEL", DEFAULT_MODEL)
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

    log.info("ai_assist.expand_start", query=query, doc_id=doc_id, model=model)

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream(
                "POST", ANTHROPIC_API_URL, json=payload, headers=headers
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
