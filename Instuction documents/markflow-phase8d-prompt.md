# MarkFlow Phase 8d — Cloud Providers + Meilisearch + Search UI
## Claude Code Session Prompt

Read `CLAUDE.md` before starting. This builds on Phase 8c (v0.8.2 base).

---

## Pre-Flight Checks

1. `docker-compose build && docker-compose up -d` — clean start
2. `pytest -q` — all 8a + 8b + 8c tests must pass
3. Upload a test MP3 via the UI and verify the transcript appears in the output

---

## Objective

This is the final Phase 8 session. It wires everything together:

1. **Cloud vision providers** — Claude, OpenAI, GPT-4o, Gemini (real implementations)
2. **Meilisearch media index** — transcripts and frame descriptions searchable
3. **Search UI updates** — media results display correctly with media type badges
4. **Settings UI polish** — final wiring and edge cases

---

## 1. Cloud Vision Providers

### `app/providers/vision_claude.py`

Implements `VisionProvider` using the Anthropic Messages API.

- API key: `await settings_manager.get_secret("vision.claude.api_key")`
- Model: `claude-opus-4-6` (use `claude-sonnet-4-6` as fallback option)

**`describe_frame()` implementation:**
```python
import httpx
import base64

async with httpx.AsyncClient(timeout=60.0) as client:
    image_data = base64.b64encode(image_path.read_bytes()).decode()
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        }
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]
```

Wrap entire method in try/except per base class graceful failure contract.

**`health_check()` implementation:**
Make a minimal API call: `POST /v1/messages` with a text-only message ("ping").
- 200 → `(True, "Claude API reachable")`
- 401 → `(False, "Invalid API key")`
- 429 → `(True, "Claude API reachable (rate limited)")` — key is valid
- Connection error → `(False, "Claude API unreachable")`

---

### `app/providers/vision_openai.py`

- API key: `await settings_manager.get_secret("vision.openai.api_key")`
- Model: `gpt-4o`
- Base URL: `https://api.openai.com/v1/chat/completions`

```python
json={
    "model": "gpt-4o",
    "max_tokens": 300,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_data}",
                    "detail": "low"   # cheaper, faster, sufficient for frame description
                }
            }
        ]
    }]
}
```

`health_check()`: GET `https://api.openai.com/v1/models` with Authorization header.
- 200 → `(True, "OpenAI API reachable")`
- 401 → `(False, "Invalid API key")`

---

### `app/providers/vision_gemini.py`

- API key: `await settings_manager.get_secret("vision.gemini.api_key")`
- Model: `gemini-1.5-flash` (cheapest vision model)
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`

```python
json={
    "contents": [{
        "parts": [
            {"text": prompt},
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_data
                }
            }
        ]
    }],
    "generationConfig": {"maxOutputTokens": 300}
}
```

Response extraction: `resp.json()["candidates"][0]["content"]["parts"][0]["text"]`

`health_check()`: minimal text-only generateContent call. Parse response for 200 vs 400/403.

---

### Update `app/providers/vision_registry.py`

Replace the stub implementations for claude/openai/gemini with the real classes.
All three now implement actual `health_check()` logic.

---

## 2. Meilisearch Media Index

### New index: `media-transcriptions`

In `app/core/meilisearch_client.py` (or wherever the Meilisearch client lives from
Phase 7), add support for the `media-transcriptions` index.

**Index settings:**
```python
MEDIA_INDEX_SETTINGS = {
    "searchableAttributes": [
        "transcript_text",
        "frame_descriptions",
        "filename",
        "title",
    ],
    "filterableAttributes": [
        "media_type",       # "audio" or "video"
        "language",
        "job_id",           # bulk job that produced this
        "enrichment_level",
    ],
    "sortableAttributes": [
        "duration_secs",
        "indexed_at",
    ],
    "displayedAttributes": [
        "id", "filename", "title", "media_type", "duration_secs",
        "language", "word_count", "scene_count", "enrichment_level",
        "source_path", "markdown_path", "indexed_at",
        # NOT transcript_text or frame_descriptions — too large for display
        # Client fetches the markdown file for full content
    ]
}
```

**Document shape:**
```python
{
    "id": sha256(source_path)[:16],   # hex, no slashes
    "filename": "quarterly-review.mp4",
    "title": "Quarterly Review",      # from DocumentModel.metadata.title
    "media_type": "video",
    "duration_secs": 1823.4,
    "language": "en",
    "word_count": 4521,
    "scene_count": 18,
    "enrichment_level": 2,
    "transcript_text": "...",          # full transcript as plain text (stripped of markdown)
    "frame_descriptions": "...",       # all frame descriptions concatenated (empty if level < 3)
    "source_path": "/mnt/source/recordings/quarterly-review.mp4",
    "markdown_path": "/mnt/output-repo/recordings/quarterly-review.md",
    "indexed_at": "2026-03-24T12:00:00Z"
}
```

**When to index:**
- After `AudioHandler` or `MediaHandler` completes successfully
- Called from `ConversionOrchestrator` after the output files are written
  (same pattern as existing document indexing in Phase 7)
- Meilisearch indexing failures are logged but never bubble up as conversion errors

**New `MeilisearchClient` methods needed:**
```python
async def index_media(self, doc: dict) -> bool
async def search_media(self, query: str, filters: dict = None, limit: int = 20) -> dict
async def delete_media(self, doc_id: str) -> bool
```

---

## 3. Search API — Media Results

### `app/api/routes/search.py` (exists from Phase 7)

Add a new endpoint or extend the existing search:

**Option A (recommended):** Extend `GET /api/search` to include media results.

Add query parameter `?include_media=true` (default: respects `search.index_media` setting).

When `include_media=true`:
- Search `media-transcriptions` index alongside existing `documents` and `adobe-files`
- Merge results: sort by Meilisearch relevance score
- Tag each result with `"result_type": "document" | "adobe" | "media"`

**Option B:** Separate endpoint `GET /api/search/media`.

Implement Option A — unified search with type tags is the better UX.

**Result shape for media hits:**
```json
{
  "result_type": "media",
  "id": "abc123def456",
  "filename": "quarterly-review.mp4",
  "title": "Quarterly Review",
  "media_type": "video",
  "duration_secs": 1823.4,
  "language": "en",
  "word_count": 4521,
  "markdown_path": "/mnt/output-repo/recordings/quarterly-review.md",
  "source_path": "/mnt/source/recordings/quarterly-review.mp4",
  "snippet": "...highlighted excerpt from transcript_text..."
}
```

---

## 4. Search UI Updates (`app/static/search.html`)

The search results page already exists from Phase 7. Update it:

**Result card for media hits:**
```
┌─────────────────────────────────────────────────────┐
│ 🎬 quarterly-review.mp4               [VIDEO] [EN]  │
│ Quarterly Review                                     │
│ Duration: 30:23 · 4,521 words · 18 scenes           │
│                                                      │
│ "...we're focused on three priorities this           │
│  quarter: efficiency, retention, and..."             │
│                                                      │
│ [ View Transcript ]  [ Open Source File ]            │
└─────────────────────────────────────────────────────┘
```

- 🎬 icon for video, 🎵 icon for audio
- `[VIDEO]` / `[AUDIO]` badge uses existing badge CSS
- `[EN]` / `[ES]` language badge
- Duration formatted as `MM:SS` or `H:MM:SS`
- "View Transcript" links to the `.md` file (served from output repo or history)
- Add a filter chip row above results: `[ All ] [ Documents ] [ Audio/Video ] [ Adobe ]`

---

## 5. Settings UI Final Wiring

**These items from 8a/8b should be verified and completed if not already done:**

- [ ] Selecting a provider in the API Keys tab saves `vision.provider` immediately
- [ ] On page load, the radio button for the active provider is selected
- [ ] The Ollama model dropdown saves `vision.ollama.model` on change
- [ ] API key fields: on blur (leaving the field), if the value is non-empty and not
  `"[set]"`, call `PUT /api/settings` to save the key. Show ✓ badge.
- [ ] API key fields: if the value IS `"[set]"` (returned by the API), show a
  "Change key" button instead of the masked field. Clicking it clears the field
  to allow entering a new value.
- [ ] "Clear key" button to explicitly remove an API key (sets it to `""`).
- [ ] Enrichment level radio buttons correctly disabled when `vision.provider == "none"`
  for level 3 (you can't use visual enrichment with no provider).

---

## 6. Cowork Search API — Media Support

The Cowork search endpoint (`GET /api/cowork/search`) from Phase 7 should include
media transcripts in its results. Update it:

- Add `media_type` to result fields
- Include transcript text excerpt in the `content` field returned to Cowork
- The Cowork endpoint's existing limit (top N results by relevance) applies across
  all result types combined

---

## Tests to Write

**`tests/test_providers_cloud.py`**
These tests should NOT make real API calls (no network in CI). Use `respx` (or
`unittest.mock.patch`) to mock `httpx.AsyncClient.post`:

- `test_claude_describe_frame_success` — mock 200 response, assert description extracted
- `test_claude_describe_frame_graceful_failure` — mock 500, assert FrameDescription with error field
- `test_claude_health_check_invalid_key` — mock 401, assert `(False, "Invalid API key")`
- `test_openai_describe_frame_success` — mock GPT-4o response structure
- `test_openai_health_check_success` — mock /v1/models 200
- `test_gemini_describe_frame_success` — mock Gemini response structure
- `test_gemini_health_check_invalid_key` — mock 403 response

**`tests/test_meilisearch_media.py`**
- `test_index_media_document` — mock MeilisearchClient, assert correct doc shape sent
- `test_search_media` — mock search response, assert result has `result_type: "media"`
- `test_meilisearch_down_does_not_fail_conversion` — if index_media raises, conversion still succeeds

**`tests/test_search_api_media.py`**
- `test_search_returns_media_results` — GET /api/search?q=test&include_media=true
- `test_search_filter_by_type` — media results can be filtered
- `test_cowork_search_includes_media` — Cowork endpoint includes media hits

---

## CLAUDE.md Update Instructions

At the end of this session, update CLAUDE.md to reflect Phase 8 complete:

```markdown
**Phase 8 complete** — Media & audio transcription with provider abstraction.
  Whisper-based transcription (audio + video), automatic codec/format detection via
  ffprobe/ffmpeg, scene detection (PySceneDetect), optional visual frame description
  via Ollama (local) / Claude / OpenAI / Gemini. Settings UI with tabbed provider
  selector, live Test Connection, Ollama model discovery. Media indexed in Meilisearch.
  Search UI shows media results with type badges. N tests passing. Tagged v0.8.3.
```

Add the new gotchas section entries:

```markdown
- **Whisper model loaded once**: WhisperTranscriptionProvider caches the loaded model
  at module level. If `transcription.whisper_model` changes in settings, the next
  call detects the mismatch and reloads. Never load per-file.

- **ffprobe required**: MediaProbe.probe() uses ffprobe subprocess. If ffprobe is not
  in PATH inside the container, all media conversions fail. Verify ffmpeg (which
  includes ffprobe) is in the Dockerfile apt-get install line.

- **Vision provider graceful contract**: describe_frame() must NEVER raise. All
  provider implementations must catch all exceptions and return FrameDescription
  with error field set. Tests verify this contract.

- **API keys encrypted**: vision.*.api_key values are Fernet-encrypted in the
  settings table. The raw secret key is in MARKFLOW_SECRET_KEY env var or
  auto-generated to app/data/secret.key. Losing the secret key means losing
  access to stored API keys — users must re-enter them.

- **media-transcriptions Meilisearch index**: Separate index from Phase 7's
  'documents' and 'adobe-files'. transcript_text is searchable but not displayed
  (too large). Client fetches the .md file for full content.
```

---

## Done Criteria

- [ ] `vision_claude.py`, `vision_openai.py`, `vision_gemini.py` all implemented
- [ ] Cloud providers follow graceful failure contract (mocked tests pass)
- [ ] `health_check()` correctly distinguishes invalid key from unreachable
- [ ] Test Connection buttons in settings UI work for all four providers
- [ ] Media transcriptions indexed to `media-transcriptions` Meilisearch index
- [ ] `GET /api/search?q=...&include_media=true` returns media hits with type tags
- [ ] Search UI shows media result cards with icons and badges
- [ ] Search UI filter chips work (All / Documents / Audio-Video / Adobe)
- [ ] Cowork search endpoint includes media results
- [ ] API Keys tab: Change key / Clear key UX works correctly
- [ ] Enrichment level 3 requires provider != none (validated in UI + server-side)
- [ ] All prior tests still pass
- [ ] Cloud provider tests pass (mocked)
- [ ] Meilisearch media tests pass (mocked)
- [ ] CLAUDE.md updated with Phase 8 complete
- [ ] Tag: `git tag v0.8.3 && git push --tags`
