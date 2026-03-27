# MarkFlow Phase 8b — Provider Abstraction + Ollama + Whisper
## Claude Code Session Prompt

Read `CLAUDE.md` before starting. This builds on Phase 8a (v0.8.0 base).

---

## Pre-Flight Checks

1. `docker-compose build && docker-compose up -d` — clean start
2. `pytest -q` — all tests from 8a must pass before you touch anything
3. Confirm `settings` and `media_transcriptions` tables exist in the DB
4. Confirm `GET /api/settings` returns 200 with expected structure

---

## Objective

Build the provider abstraction layer and implement the two local providers:

- **`WhisperTranscriptionProvider`** — audio transcription, always available, no API key
- **`OllamaVisionProvider`** — visual frame description via local Ollama/LLaVA

Also wire up the Test Connection buttons in the settings UI that were placeholders in 8a.

This session does NOT build the MediaHandler or AudioHandler (that's 8c). Providers
are standalone — they can be tested independently via the API.

---

## New Package: `app/providers/`

Create `app/providers/__init__.py` (empty, just marks it as a package).

---

### 1. `app/providers/transcription_base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str
    confidence: float | None = None  # 0.0–1.0 if available

@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str           # detected language code, e.g. "en"
    duration_secs: float
    word_count: int
    provider_id: str

class TranscriptionProvider(ABC):
    provider_id: str
    display_name: str

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,           # always a WAV or MP3 temp file — normalized by media_probe
        language: str = "auto",     # "auto" or ISO 639-1 code
    ) -> TranscriptionResult: ...

    @abstractmethod
    async def health_check(self) -> tuple[bool, str]:
        """Returns (is_available, status_message)."""
        ...
```

---

### 2. `app/providers/transcription_whisper.py`

Implements `TranscriptionProvider` using `openai-whisper` (local, no API key).

**Critical implementation details:**

- Load the model ONCE. Cache the loaded model as a module-level variable.
  Model size comes from `SettingsManager.get("transcription.whisper_model")`.
  If the model size changes in settings, reload on next call.

- `transcribe()` is CPU-bound. Wrap with `asyncio.to_thread()`.

- Input audio can be any format ffmpeg supports — Whisper internally calls ffmpeg.
  Do not pre-convert. Pass the path directly to `whisper.load_audio()`.

- Map Whisper's segment output to `TranscriptSegment`:
  - `segment["start"]` → `start_sec`
  - `segment["end"]` → `end_sec`
  - `segment["text"].strip()` → `text`
  - No per-segment confidence from Whisper base — leave as `None`

- `language="auto"` → pass `None` to `whisper.transcribe(language=None)`.
  Any other value → pass directly.

- `health_check()` → try importing whisper and loading the smallest model
  (`tiny`). If that works, return `(True, "Whisper available (tiny test OK)")`.
  If import fails, return `(False, "openai-whisper not installed")`.

---

### 3. `app/providers/vision_base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FrameDescription:
    frame_path: Path
    timestamp_sec: float
    description: str
    provider_id: str
    error: str | None = None        # populated if the call failed gracefully

class VisionProvider(ABC):
    provider_id: str
    display_name: str
    requires_api_key: bool
    supports_local: bool

    @abstractmethod
    async def describe_frame(
        self,
        image_path: Path,
        prompt: str,
    ) -> FrameDescription: ...

    @abstractmethod
    async def health_check(self) -> tuple[bool, str]: ...
```

**Graceful failure contract:**
`describe_frame()` must NEVER raise. If the provider call fails for any reason,
return a `FrameDescription` with `description=""` and
`error="[vision unavailable — {reason}]"`. Log the error via structlog but swallow
the exception. The handler in 8c will insert the error string into the transcript.

---

### 4. `app/providers/vision_ollama.py`

Implements `VisionProvider` for Ollama.

- Base URL comes from `SettingsManager.get("vision.ollama.base_url")`.
- Model comes from `SettingsManager.get("vision.ollama.model")`.
- Use `httpx.AsyncClient` (already a dependency from Phase 7).

**`describe_frame()` implementation:**
1. Read the image file, base64-encode it.
2. POST to `{base_url}/api/generate`:
   ```json
   {
     "model": "{model}",
     "prompt": "{prompt}",
     "images": ["{base64_image}"],
     "stream": false
   }
   ```
3. Extract `response["response"]` as the description text.
4. Timeout: 60 seconds. On timeout, return graceful error.

**`health_check()` implementation:**
1. GET `{base_url}/api/tags` (lists installed models).
2. If 200: check if the configured model is in the response.
   - If model found: return `(True, f"Ollama reachable, {model} available")`
   - If model not found: return `(True, f"Ollama reachable, but {model} not installed")`
     Note: still returns True (Ollama itself is up) — the UI can show a warning.
3. If connection error: `(False, "Ollama unreachable at {base_url}")`
4. Timeout: 5 seconds.

**`get_available_models()` — extra method (not in base class):**
Calls `GET {base_url}/api/tags`, returns `list[str]` of model names.
Used by the settings API to populate the model dropdown.
Returns `[]` on any error.

---

### 5. `app/providers/vision_registry.py`

```python
# Maps provider_id → VisionProvider instance (lazy-initialized singletons)
class VisionRegistry:
    _instances: dict[str, VisionProvider] = {}

    @classmethod
    def get(cls, provider_id: str) -> VisionProvider | None:
        """Returns None for provider_id='none'."""
        ...

    @classmethod
    def all_providers(cls) -> list[dict]:
        """Returns static metadata list for the /api/settings/providers endpoint."""
        ...
```

Register: `none`, `ollama`, `claude`, `openai`, `gemini`.
The claude/openai/gemini implementations are stubs in 8b — they return
`(False, "Not yet implemented — coming in Phase 8d")` from `health_check()`.

---

### 6. `app/providers/transcription_registry.py`

Same pattern as vision registry. Only `whisper` is registered in 8b.

---

## Files to Modify

### `app/api/routes/settings.py` — add these endpoints

```
GET  /api/settings/providers/vision/{provider_id}/test
     Calls provider.health_check() and returns:
     { "provider": "ollama", "available": true, "message": "Ollama reachable, llava available" }
     Timeout: 10 seconds total. Returns 200 even if provider unavailable (check "available" field).

GET  /api/settings/providers/vision/ollama/models
     Calls OllamaVisionProvider.get_available_models().
     Returns: { "models": ["llava", "bakllava", "llava-llama3"] }
     Returns { "models": [] } if Ollama unreachable — never 500.

GET  /api/settings/providers/transcription/whisper/test
     Same pattern — calls WhisperTranscriptionProvider.health_check().
```

### `app/static/settings.html` — wire up placeholder buttons

Replace "Coming soon" alert handlers with real fetch calls:

- **Test Connection buttons**: call `/api/settings/providers/vision/{id}/test`,
  show a status badge next to the button:
  - 🟢 green dot + message if `available: true`
  - 🔴 red dot + message if `available: false`
  The badge auto-clears after 8 seconds.

- **Ollama model dropdown**: on page load (and after "Test Connection" succeeds),
  fetch `/api/settings/providers/vision/ollama/models` and populate the `<select>`.
  If the endpoint returns `[]`, show a disabled dropdown with "Ollama unreachable".
  The current saved model value should be selected if it appears in the list.

### `requirements.txt`

Add:
```
openai-whisper
```

Note: `openai-whisper` pulls in `torch` as a dependency. This will significantly
increase Docker image build time on first build (~2GB). Accept this — it's required.
Add a comment in `requirements.txt`: `# openai-whisper pulls torch — large image`

Also add to `docker-compose.yml` under the markflow service, if not already present:
```yaml
environment:
  - MARKFLOW_SECRET_KEY=${MARKFLOW_SECRET_KEY:-}
```

---

## Tests to Write

**`tests/test_providers_whisper.py`**
- `test_whisper_health_check` — returns (True, ...) when whisper is installed
- `test_whisper_transcribe_wav` — transcribe a short test WAV file, assert segments > 0
  (generate a test WAV with `wave` stdlib — 2 seconds of silence is fine, Whisper
  will produce an empty or minimal transcript, but no exception)
- `test_whisper_transcribe_returns_language` — language field is a string

**`tests/test_providers_ollama.py`**
- `test_ollama_health_check_unreachable` — point at a bad URL, assert `(False, ...)`
- `test_ollama_get_models_unreachable` — returns `[]`, no exception
- `test_ollama_describe_frame_graceful_failure` — on connection error, returns
  `FrameDescription` with `error` field set, no exception raised

**`tests/test_settings_provider_api.py`**
- `test_test_vision_provider_returns_200` — even when unreachable, returns HTTP 200
- `test_test_whisper_provider` — returns `available: true`
- `test_ollama_models_unreachable` — returns `{ "models": [] }`

---

## Done Criteria

- [ ] `app/providers/` package exists with all files from this session
- [ ] `WhisperTranscriptionProvider.transcribe()` works on a test WAV
- [ ] `WhisperTranscriptionProvider.health_check()` returns `(True, ...)` in Docker
- [ ] `OllamaVisionProvider.health_check()` returns `(False, ...)` gracefully
  when Ollama is not running (expected in CI/test environment)
- [ ] `OllamaVisionProvider.describe_frame()` never raises — always returns
  a `FrameDescription` even on failure
- [ ] `GET /api/settings/providers/vision/ollama/test` returns 200 with
  `{ "available": false, ... }` when Ollama not running
- [ ] `GET /api/settings/providers/vision/ollama/models` returns `{ "models": [] }`
  when Ollama not running
- [ ] Settings UI Test Connection buttons show live status badge
- [ ] Ollama model dropdown populates from API (or shows "unreachable")
- [ ] All prior tests still pass
- [ ] New provider tests pass
- [ ] CLAUDE.md updated with v0.8.1 status
- [ ] Tag: `git tag v0.8.1 && git push --tags`
