# MarkFlow Changeset: Visual Enrichment Pipeline
# Scene detection, keyframe extraction, and provider-based frame description
# Ollama (local) · OpenAI · Gemini · Encrypted API key storage

**Version:** v1.0
**Targets:** v0.8.1 tag
**Prerequisite:** v0.8.0 complete (media transcription pipeline applied and tagged)
**Scope:** Visual enrichment for video files. Adds scene detection, keyframe extraction,
and optional AI frame descriptions via a pluggable provider layer. New encrypted settings
store for API keys. No changes to audio-only pipeline or caption ingestor.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. This changeset builds directly on v0.8.0's
media transcription pipeline. The two changesets are designed to be sequential — v0.8.0
handles the audio track (transcription), v0.8.1 handles the video track (visual context).

**What v0.8.0 built that this changeset extends:**
- `core/media_orchestrator.py` — top-level coordinator (we modify this)
- `core/transcript_formatter.py` — Markdown/SRT/VTT output (we modify this)
- `core/media_router.py` — type detection (we import, do not modify)
- `core/audio_extractor.py` — duration + WAV extraction (we import, do not modify)
- `static/settings.html` — transcription section (we add a new Vision section)
- Meilisearch `transcripts` index (we add `frame_descriptions` field to it)

**What this changeset does NOT touch:**
- `core/whisper_transcriber.py` — no changes
- `core/cloud_transcriber.py` — no changes (cloud transcription ≠ cloud vision)
- `core/transcription_engine.py` — no changes
- `core/caption_ingestor.py` — no changes
- Bulk scanner — no changes (media files already picked up in v0.8.0)
- Audio-only handler path — visual enrichment is video-only; audio files are unchanged

**Provider support — vision vs. transcription (different concerns, different APIs):**

| Provider   | Transcription (v0.8.0) | Frame Description (v0.8.1) |
|------------|------------------------|---------------------------|
| Anthropic  | ❌ No audio support     | ✅ Claude Vision API       |
| OpenAI     | ✅ Whisper API          | ✅ GPT-4o vision           |
| Gemini     | ✅ Audio inline         | ✅ Gemini 1.5 Flash vision |
| Ollama     | ❌ No audio support     | ✅ LLaVA / BakLLaVA local  |

Note: Anthropic is excluded from transcription (v0.8.0) but **is** a valid vision
provider here because Claude Vision accepts images, not audio.

---

## 1. Architecture Overview

```
Video file (.mp4, .mov, .mkv, etc.)
        ↓
MediaOrchestrator.process_file()  ← extended, not replaced
        ↓
  [v0.8.0 track — unchanged]          [v0.8.1 track — new]
  AudioExtractor.extract()             SceneDetector.detect_scenes()
        ↓                                      ↓
  TranscriptionEngine.transcribe()     KeyframeExtractor.extract_keyframes()
        ↓                                      ↓
  TranscriptResult                     list[SceneKeyframe]
        ↓                                      ↓
        └──────────────┬────────────────────────┘
                       ↓
             VisualEnrichmentEngine.enrich()
                       ↓
             list[SceneDescription]   ← may have error field if provider failed
                       ↓
             TranscriptFormatter.to_markdown()  ← modified: merges scenes into transcript
             TranscriptFormatter.to_srt()       ← unchanged
             TranscriptFormatter.to_vtt()       ← unchanged
                       ↓
             output/transcript.md   ← now includes scene description blocks
             output/transcript.srt  ← unchanged (no visual content in captions)
             output/transcript.vtt  ← unchanged
             output/_markflow/transcript.meta.json  ← extended with scene fields
             output/_markflow/frames/scene_NNN.jpg  ← keyframes (if save_keyframes=true)
                       ↓
             SearchIndexer.index_transcript()  ← extended with frame_descriptions field
```

---

## 2. Dependencies

### `requirements.txt` (modify)

Add:
```
scenedetect[opencv]     # PySceneDetect — scene boundary detection
cryptography            # Fernet encryption for API keys at rest
```

Note: `opencv-python-headless` is pulled in by `scenedetect[opencv]`. Use the
headless variant (no GUI) — appropriate for Docker/server use. If `opencv-python`
(full GUI) is already installed from another dependency, PySceneDetect will use it.
Do not install both.

`ffmpeg` is already installed in the Dockerfile from v0.8.0 (audio extraction).
Keyframe extraction uses the same `ffmpeg` binary — no additional system package needed.

### `.env.example` (modify)

Add:
```bash
# Visual enrichment (v0.8.1)
VISION_ENABLED=false            # master on/off switch
                                # false by default — expensive, requires provider setup
VISION_ENRICHMENT_LEVEL=2       # 1=metadata only | 2=+transcription | 3=+frame descriptions
                                # level 3 requires VISION_ENABLED=true + configured provider
VISION_PROVIDER=ollama          # ollama | openai | gemini | anthropic
VISION_FRAME_LIMIT=50           # max keyframes per video (caps cost + time)
VISION_SAVE_KEYFRAMES=false     # save keyframe JPEGs to _markflow/frames/
                                # useful for debugging, false by default (disk space)
MARKFLOW_SECRET_KEY=            # leave blank to auto-generate on first boot
                                # if set, must be a valid Fernet key (32 url-safe base64 bytes)
                                # generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### `docker-compose.yml` (modify)

Pass the secret key into the container:
```yaml
environment:
  - MARKFLOW_SECRET_KEY=${MARKFLOW_SECRET_KEY:-}
```

Add a named volume for the auto-generated key file (persists across container rebuilds):
```yaml
volumes:
  - markflow-secrets:/app/data/secrets

# Add to volumes section at bottom:
  markflow-secrets:
```

---

## 3. Database Changes

### `core/database.py` (modify)

#### New table: `settings`

Stores encrypted API keys and provider configuration. Separate from the
`preferences` table — preferences are user-facing UI options, settings are
system-level and may contain secrets.

```sql
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,          -- Fernet-encrypted for .api_key keys,
                                        -- plaintext for all others
    is_encrypted INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Add with `CREATE TABLE IF NOT EXISTS` — idempotent, safe to run on existing DB.

#### Extend `conversion_history` (add columns if missing)

Add visual enrichment columns. Use the existing `_add_column_if_missing` pattern:

```sql
vision_provider     TEXT        -- 'ollama' | 'openai' | 'gemini' | 'anthropic' | null
vision_model        TEXT        -- model used e.g. 'llava', 'gpt-4o' (null if no vision)
scene_count         INTEGER     -- number of detected scenes (null for audio, 0 if none)
keyframe_count      INTEGER     -- keyframes extracted (null for audio)
frame_desc_count    INTEGER     -- frames that got descriptions (null for audio)
enrichment_level    INTEGER     -- 1/2/3 at time of conversion
```

#### New table: `scene_keyframes`

Stores per-scene metadata. Enables rebuilding visual content without re-processing
the video. Parallel to `transcript_segments` from v0.8.0.

```sql
CREATE TABLE IF NOT EXISTS scene_keyframes (
    id              TEXT PRIMARY KEY,   -- UUID
    history_id      TEXT NOT NULL,      -- references conversion_history.id
    scene_index     INTEGER NOT NULL,   -- 0-based
    start_seconds   REAL NOT NULL,      -- scene start time
    end_seconds     REAL NOT NULL,      -- scene end time
    midpoint_seconds REAL NOT NULL,     -- timestamp of extracted keyframe
    keyframe_path   TEXT,               -- relative path to .jpg (null if not saved)
    description     TEXT,               -- frame description text (null if level < 3)
    description_error TEXT,             -- error message if vision call failed
    provider        TEXT,               -- provider used for this frame
    FOREIGN KEY(history_id) REFERENCES conversion_history(id)
);
CREATE INDEX IF NOT EXISTS idx_keyframes_history
    ON scene_keyframes(history_id, scene_index);
```

#### New DB helpers

```python
async def record_scene_keyframes(history_id: str,
                                  scenes: list[dict]) -> None:
    """
    Bulk insert scene records. Each dict:
    { scene_index, start_seconds, end_seconds, midpoint_seconds,
      keyframe_path, description, description_error, provider }
    """

async def get_scene_keyframes(history_id: str) -> list[dict]:
    """Return all scene records for a history entry, ordered by scene_index."""

async def update_history_vision_stats(
    history_id: str,
    vision_provider: str | None,
    vision_model: str | None,
    scene_count: int,
    keyframe_count: int,
    frame_desc_count: int,
    enrichment_level: int
) -> None:
```

---

## 4. Encrypted Settings Manager

### `core/settings_manager.py` (new file)

Handles all read/write to the `settings` table, with transparent Fernet
encryption for keys that end in `.api_key`.

```python
from cryptography.fernet import Fernet
import os, base64, structlog
from pathlib import Path

log = structlog.get_logger(__name__)

SECRET_KEY_FILE = Path("/app/data/secrets/markflow.key")

# Keys that are encrypted at rest. Any key ending in .api_key is auto-encrypted.
ENCRYPTED_KEY_SUFFIX = ".api_key"

# All known settings keys with their defaults.
# Non-sensitive defaults — API keys always default to empty string.
SETTINGS_DEFAULTS: dict[str, str] = {
    "vision.provider":              "ollama",
    "vision.enabled":               "false",
    "vision.enrichment_level":      "2",
    "vision.frame_limit":           "50",
    "vision.save_keyframes":        "false",
    "vision.ollama.base_url":       "http://host.docker.internal:11434",
    "vision.ollama.model":          "llava",
    "vision.openai.api_key":        "",     # encrypted
    "vision.gemini.api_key":        "",     # encrypted
    "vision.anthropic.api_key":     "",     # encrypted
    "vision.frame_prompt": (
        "Describe this frame from a video. Note any visible text, slides, "
        "diagrams, charts, people, or on-screen graphics. Be concise and factual. "
        "Do not describe what you cannot see clearly."
    ),
}

class SettingsManager:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        """
        Lazy-initialize Fernet cipher.
        Key source (in order):
          1. MARKFLOW_SECRET_KEY env var (base64url-encoded Fernet key)
          2. SECRET_KEY_FILE on disk (auto-generated if missing)
        """
        if self._fernet:
            return self._fernet

        raw_key = os.environ.get("MARKFLOW_SECRET_KEY", "").strip()
        if raw_key:
            self._fernet = Fernet(raw_key.encode())
            return self._fernet

        # Auto-generate and persist
        SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if SECRET_KEY_FILE.exists():
            raw_key = SECRET_KEY_FILE.read_text().strip()
        else:
            raw_key = Fernet.generate_key().decode()
            SECRET_KEY_FILE.write_text(raw_key)
            SECRET_KEY_FILE.chmod(0o600)
            log.info("settings.secret_key_generated",
                     path=str(SECRET_KEY_FILE))

        self._fernet = Fernet(raw_key.encode())
        return self._fernet

    def _should_encrypt(self, key: str) -> bool:
        return key.endswith(ENCRYPTED_KEY_SUFFIX)

    def _encrypt(self, value: str) -> str:
        """Encrypt a plaintext value. Returns base64 ciphertext string."""
        return self._get_fernet().encrypt(value.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string. Returns plaintext."""
        return self._get_fernet().decrypt(ciphertext.encode()).decode()

    async def get(self, key: str) -> str:
        """
        Get a setting value. Returns default if not set.
        For encrypted keys, returns the DECRYPTED value.
        Callers (provider classes) receive plaintext.
        """

    async def get_bool(self, key: str) -> bool:
        return (await self.get(key)).lower() == "true"

    async def get_int(self, key: str) -> int:
        return int(await self.get(key))

    async def set(self, key: str, value: str) -> None:
        """
        Set a setting value. Encrypts automatically if key ends in .api_key.
        Raises ValueError if key not in SETTINGS_DEFAULTS.
        """
        if key not in SETTINGS_DEFAULTS:
            raise ValueError(f"Unknown settings key: {key}")
        if self._should_encrypt(key) and value:
            stored_value = self._encrypt(value)
            is_encrypted = 1
        else:
            stored_value = value
            is_encrypted = 0
        # upsert into settings table via aiosqlite

    async def get_all_public(self) -> dict[str, str]:
        """
        Return all settings as a dict suitable for API responses.
        Encrypted keys with a non-empty value → "[set]"
        Encrypted keys with empty value → ""
        All other keys → plaintext value
        NEVER returns ciphertext or decrypted API keys.
        """

    async def set_many(self, updates: dict[str, str]) -> None:
        """Bulk update. Validates all keys before writing any."""

    async def reset_to_defaults(self) -> None:
        """Delete all rows from settings table (defaults re-applied on next get)."""

    async def key_is_set(self, key: str) -> bool:
        """Returns True if an encrypted key has a non-empty stored value."""
```

**Security contract:**
- `get()` — returns decrypted plaintext. For use by provider classes only.
- `get_all_public()` — returns `"[set]"` or `""` for `.api_key` keys. For use by API routes.
- Raw ciphertext is NEVER returned by any public method.
- Fernet key is never logged. Log calls that mention settings must not include values.
- If decryption fails (key rotation, corrupted value), log the error and return `""`.
  Do not raise — a corrupted stored key is not worse than an unset key.

---

## 5. Scene Detector

### `core/scene_detector.py` (new file)

Detects scene boundaries in video files using PySceneDetect.

```python
from dataclasses import dataclass
from pathlib import Path
import structlog

log = structlog.get_logger(__name__)

@dataclass
class SceneBoundary:
    index: int              # 0-based
    start_seconds: float
    end_seconds: float
    midpoint_seconds: float

class SceneDetector:
    def __init__(self, frame_limit: int = 50):
        """
        frame_limit: maximum number of scenes to return.
        If more scenes are detected, downsample evenly to frame_limit.
        Prevents runaway costs on highly-edited videos.
        """
        self._frame_limit = frame_limit

    async def detect(self, video_path: Path) -> list[SceneBoundary]:
        """
        Run PySceneDetect on the video in asyncio.to_thread().
        Returns list of SceneBoundary, sorted by start_seconds.

        Algorithm:
          from scenedetect import detect, ContentDetector
          scenes = detect(str(video_path), ContentDetector())

        ContentDetector uses frame-difference threshold.
        Default threshold (27.0) works well for most content.
        No tuning needed — keep default.

        If detect() returns 0 scenes (static video, animation, screen recording):
          Return a single SceneBoundary covering the whole video.
          This ensures at least one keyframe is always extracted.

        If detect() raises (corrupt video, unsupported codec):
          Log the error, return single-scene fallback.
          Never raises — scene detection failure is non-fatal.
        """

    def _build_scenes(self, raw_scenes: list,
                       duration: float) -> list[SceneBoundary]:
        """
        Convert PySceneDetect output to SceneBoundary list.
        raw_scenes: list of (start_timecode, end_timecode) tuples.

        Downsample if len > frame_limit:
          Keep first scene, last scene, and sample evenly from the middle.
          This preserves intro/outro context while reducing density.
        """

    def _downsample(self, scenes: list[SceneBoundary]) -> list[SceneBoundary]:
        """Evenly sample scenes down to self._frame_limit."""
```

**Handling edge cases:**

| Condition | Behavior |
|-----------|----------|
| 0 scenes detected | Return 1 scene covering full video |
| 1 scene (whole video) | Return as-is, midpoint = duration/2 |
| > frame_limit scenes | Downsample evenly, always keep first + last |
| PySceneDetect import fails | Log error, return 1-scene fallback |
| Video codec unsupported by OpenCV | Log error, return 1-scene fallback |

Screen recordings, slideshows, and lecture captures often have very few cuts —
the 1-scene fallback produces a single descriptive keyframe, which is appropriate.

---

## 6. Keyframe Extractor

### `core/keyframe_extractor.py` (new file)

Extracts a single JPEG frame at the midpoint of each scene using ffmpeg.

```python
from dataclasses import dataclass
from pathlib import Path
import structlog, asyncio, subprocess, tempfile

log = structlog.get_logger(__name__)

@dataclass
class SceneKeyframe:
    scene: SceneBoundary        # from scene_detector.py
    image_path: Path            # path to extracted JPEG (in tmp_dir)
    extraction_error: str | None  # None if successful

class KeyframeExtractor:
    async def extract(
        self,
        video_path: Path,
        scenes: list[SceneBoundary],
        tmp_dir: Path,
        output_dir: Path | None = None,  # if set, also copy to persistent storage
    ) -> list[SceneKeyframe]:
        """
        Extract one JPEG per scene, at the scene's midpoint_seconds.
        All extractions run concurrently (asyncio.gather with a semaphore of 4).
        Returns list[SceneKeyframe] in the same order as scenes input.
        Failed extractions have extraction_error set — never raises.

        Output filenames: scene_000.jpg, scene_001.jpg, ...
        Written to tmp_dir during processing.
        If output_dir is provided (save_keyframes=true), also copied there.
        """

    async def _extract_one(
        self,
        video_path: Path,
        scene: SceneBoundary,
        tmp_dir: Path,
        semaphore: asyncio.Semaphore,
    ) -> SceneKeyframe:
        """
        ffmpeg command:
          ffmpeg -ss {midpoint} -i {video_path}
                 -frames:v 1 -q:v 3
                 {tmp_dir}/scene_{index:03d}.jpg -y

        -ss before -i: fast seek (keyframe seek, may be imprecise by ±2s)
        -q:v 3: JPEG quality 1-31, lower is better. 3 is good balance.
        Timeout: 30 seconds per frame. On timeout, return error SceneKeyframe.
        """
```

**Quality settings:**
JPEG quality `-q:v 3` produces ~150–400KB images. Suitable for vision API calls
that have image size limits. For local Ollama, larger is better but the difference
is minor for frame description tasks. `-q:v 3` is a safe default for all providers.

**Concurrency:**
Run up to 4 frame extractions simultaneously. More than 4 concurrent ffmpeg
processes on a typical Docker host causes I/O contention with diminishing returns.
`asyncio.Semaphore(4)` enforces this limit.

---

## 7. Vision Providers

### `core/vision_providers/__init__.py` (new package)

Empty file, marks the directory as a Python package.

### `core/vision_providers/base.py` (new file)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FrameDescription:
    scene_index: int
    description: str
    provider_id: str
    model: str
    error: str | None = None    # set if the call failed gracefully

class VisionProvider(ABC):
    provider_id: str
    display_name: str
    requires_api_key: bool
    supports_local: bool
    default_model: str

    @abstractmethod
    async def describe_frame(
        self,
        image_path: Path,
        prompt: str,
        scene_index: int,
    ) -> FrameDescription:
        """
        Describe a single image frame.

        MUST NEVER RAISE. If the API call fails for any reason:
          - Log the error via structlog
          - Return FrameDescription with description="" and error="[reason]"
          - Do not propagate exceptions

        Implementations are responsible for:
          - Loading their API key from SettingsManager
          - Respecting a 60-second timeout per call
          - Encoding the image as base64 if required by the API
        """

    @abstractmethod
    async def health_check(self) -> tuple[bool, str]:
        """
        Fast connectivity check (5-second timeout).
        Returns (is_available, human_readable_status_message).

        Must not raise. Connection errors → (False, "reason").
        Invalid API key → (False, "Invalid API key").
        Rate limited but key is valid → (True, "reachable (rate limited)").
        """

    @abstractmethod
    async def get_available_models(self) -> list[str]:
        """
        Returns list of models usable for vision tasks.
        Returns [] on any error — never raises.
        For fixed-model providers (OpenAI, Gemini, Anthropic): return [default_model].
        For Ollama: query /api/tags, return models that support vision.
        """
```

### `core/vision_providers/ollama_provider.py` (new file)

```python
class OllamaVisionProvider(VisionProvider):
    provider_id = "ollama"
    display_name = "Ollama (local)"
    requires_api_key = False
    supports_local = True
    default_model = "llava"

    """
    Uses Ollama's /api/generate endpoint with base64 image input.
    No API key required — uses base URL from settings.

    POST {base_url}/api/generate
    {
      "model": "{model}",
      "prompt": "{prompt}",
      "images": ["{base64_jpeg}"],
      "stream": false
    }

    Response: { "response": "description text" }

    health_check():
      GET {base_url}/api/tags
      If 200 and configured model in response → (True, "Ollama · {model} available")
      If 200 but model missing → (True, "Ollama reachable · {model} not installed")
        Note: True because Ollama itself is up — the UI can warn about the model.
      If connection error → (False, "Ollama unreachable at {base_url}")

    get_available_models():
      GET {base_url}/api/tags → parse model names.
      Vision-capable models heuristic: name contains 'llava', 'bakllava',
      'llava-llama3', 'moondream', 'minicpm-v', 'cogvlm', 'internvl'.
      If the tags list is empty or the endpoint fails: return [].
    """
```

### `core/vision_providers/openai_provider.py` (new file)

```python
class OpenAIVisionProvider(VisionProvider):
    provider_id = "openai"
    display_name = "OpenAI (GPT-4o)"
    requires_api_key = True
    supports_local = False
    default_model = "gpt-4o"

    """
    Uses OpenAI Chat Completions API with image_url content block.

    POST https://api.openai.com/v1/chat/completions
    Authorization: Bearer {api_key}
    {
      "model": "gpt-4o",
      "max_tokens": 300,
      "messages": [{
        "role": "user",
        "content": [
          { "type": "text", "text": "{prompt}" },
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,{base64_jpeg}",
              "detail": "low"   ← cheaper, sufficient for frame description
            }
          }
        ]
      }]
    }

    Response: choices[0].message.content

    health_check():
      GET https://api.openai.com/v1/models
      Authorization: Bearer {api_key}
      200 → (True, "OpenAI API reachable")
      401 → (False, "Invalid API key")
      429 → (True, "OpenAI reachable (rate limited)")
      Connection error → (False, "OpenAI API unreachable")

    get_available_models():
      Return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"] — fixed list.
      Do not query the models endpoint (it returns hundreds of models).
    """
```

**Cost note — document in settings UI:**
GPT-4o with `detail: low` costs approximately $0.001–$0.003 per frame.
A 60-minute video with 50 scenes ≈ $0.05–$0.15. Document this.

### `core/vision_providers/gemini_provider.py` (new file)

```python
class GeminiVisionProvider(VisionProvider):
    provider_id = "gemini"
    display_name = "Google Gemini"
    requires_api_key = True
    supports_local = False
    default_model = "gemini-1.5-flash"

    """
    Uses Gemini generateContent endpoint with inline base64 image.

    POST https://generativelanguage.googleapis.com/v1beta/models/
         {model}:generateContent?key={api_key}
    {
      "contents": [{
        "parts": [
          { "text": "{prompt}" },
          {
            "inline_data": {
              "mime_type": "image/jpeg",
              "data": "{base64_jpeg}"
            }
          }
        ]
      }],
      "generationConfig": { "maxOutputTokens": 300 }
    }

    Response: candidates[0].content.parts[0].text

    health_check():
      POST same endpoint with text-only content (no image), minimal prompt.
      200 → (True, "Gemini API reachable")
      400/403 → (False, "Invalid API key")
      Connection error → (False, "Gemini API unreachable")

    get_available_models():
      Return ["gemini-1.5-flash", "gemini-1.5-pro"] — fixed list.
      1.5 Flash is cheaper and fast enough for frame description.
      1.5 Pro is higher quality but slower and more expensive.
    """
```

### `core/vision_providers/anthropic_provider.py` (new file)

```python
class AnthropicVisionProvider(VisionProvider):
    provider_id = "anthropic"
    display_name = "Anthropic (Claude)"
    requires_api_key = True
    supports_local = False
    default_model = "claude-sonnet-4-6"

    """
    Uses Anthropic Messages API with base64 image content block.

    POST https://api.anthropic.com/v1/messages
    x-api-key: {api_key}
    anthropic-version: 2023-06-01
    {
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
              "data": "{base64_jpeg}"
            }
          },
          { "type": "text", "text": "{prompt}" }
        ]
      }]
    }

    Response: content[0].text

    health_check():
      POST /v1/messages with text-only message (no image, tiny prompt).
      200 → (True, "Anthropic API reachable")
      401 → (False, "Invalid API key")
      429 → (True, "Anthropic reachable (rate limited)")
      Connection error → (False, "Anthropic API unreachable")

    get_available_models():
      Return ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"]
      Fixed list — Anthropic does not expose a public models list endpoint.
    """
```

### `core/vision_providers/registry.py` (new file)

```python
from .ollama_provider import OllamaVisionProvider
from .openai_provider import OpenAIVisionProvider
from .gemini_provider import GeminiVisionProvider
from .anthropic_provider import AnthropicVisionProvider
from .base import VisionProvider

_PROVIDERS: dict[str, type[VisionProvider]] = {
    "ollama":     OllamaVisionProvider,
    "openai":     OpenAIVisionProvider,
    "gemini":     GeminiVisionProvider,
    "anthropic":  AnthropicVisionProvider,
}

def get_provider(provider_id: str,
                 settings_manager) -> VisionProvider | None:
    """
    Returns an instance of the requested provider, or None if provider_id is
    'none' or unknown. Provider instances are lightweight — instantiated per call,
    not cached as singletons (they hold no expensive state).
    """

def all_provider_metadata() -> list[dict]:
    """
    Returns static metadata list for the /api/settings/providers endpoint.
    Does NOT do live health checks.
    [
      { "id": "ollama", "display_name": "Ollama (local)",
        "requires_api_key": false, "supports_local": true,
        "default_model": "llava" },
      ...
    ]
    """

def provider_ids() -> list[str]:
    return list(_PROVIDERS.keys())
```

---

## 8. Visual Enrichment Engine

### `core/visual_enrichment_engine.py` (new file)

Orchestrates scene detection → keyframe extraction → frame description.
This is the high-level coordinator for the visual track.

```python
@dataclass
class EnrichmentResult:
    scenes: list[SceneBoundary]
    keyframes: list[SceneKeyframe]
    descriptions: list[FrameDescription]   # may have error entries
    provider_id: str | None                # None if enrichment_level < 3
    model: str | None
    enrichment_level: int
    total_scenes: int
    described_scenes: int                  # frames that got real descriptions
    failed_scenes: int                     # frames with error entries

class VisualEnrichmentEngine:
    def __init__(self, settings_manager: SettingsManager):
        self._settings = settings_manager

    async def enrich(
        self,
        video_path: Path,
        duration_seconds: float,
        tmp_dir: Path,
        output_dir: Path,               # for optional keyframe saving
    ) -> EnrichmentResult:
        """
        Full visual enrichment pipeline:

        1. Read settings:
             level = settings.get_int("vision.enrichment_level")
             enabled = settings.get_bool("vision.enabled")
             provider_id = settings.get("vision.provider")
             frame_limit = settings.get_int("vision.frame_limit")
             save_keyframes = settings.get_bool("vision.save_keyframes")

        2. Scene detection (always runs for video, regardless of level):
             detector = SceneDetector(frame_limit=frame_limit)
             scenes = await detector.detect(video_path)

        3. Keyframe extraction (always runs for video):
             persistent_dir = output_dir / "_markflow" / "frames" if save_keyframes else None
             extractor = KeyframeExtractor()
             keyframes = await extractor.extract(video_path, scenes, tmp_dir, persistent_dir)

        4. Frame description (only if enabled=true AND level >= 3):
             If not enabled or level < 3:
               Return EnrichmentResult with descriptions=[] (no provider called)

             provider = VisionRegistry.get_provider(provider_id, self._settings)
             If provider is None:
               Return EnrichmentResult with descriptions=[]

             prompt = settings.get("vision.frame_prompt")
             Run describe_frame() concurrently for all keyframes.
             Use asyncio.Semaphore(3) — max 3 concurrent API calls.
             (Lower than keyframe extraction because API calls are expensive)

        5. Return EnrichmentResult with all data populated.
        """

    async def _describe_all(
        self,
        provider: VisionProvider,
        keyframes: list[SceneKeyframe],
        prompt: str,
    ) -> list[FrameDescription]:
        """
        Describe all keyframes concurrently with semaphore(3).
        Failed keyframes (extraction_error set) produce a FrameDescription
        with error="[keyframe extraction failed — {reason}]" without calling the API.
        """
```

---

## 9. MediaOrchestrator Integration

### `core/media_orchestrator.py` (modify)

**Do not rewrite this file.** Add visual enrichment as an additional step
after transcription. The existing transcription pipeline is unchanged.

Add `VisualEnrichmentEngine` initialization in `__init__`:

```python
def __init__(self, db_path, whisper_config, llm_provider,
             search_indexer, settings_manager):  # ← add settings_manager param
    # ... existing init ...
    self._visual_engine = VisualEnrichmentEngine(settings_manager)
```

Extend `process_file()` — add after step 2 (transcription), before step 3 (formatting):

```python
# Step 2b: Visual enrichment (video only, audio and captions skip this)
enrichment: EnrichmentResult | None = None
if media_type == "video":
    enrichment = await self._visual_engine.enrich(
        video_path=source_path,
        duration_seconds=audio_duration,
        tmp_dir=tmp_dir,
        output_dir=output_md_path.parent,
    )
```

Pass `enrichment` into `TranscriptFormatter`:

```python
# Step 3: Format output
md_content = self._formatter.to_markdown(
    result=transcript_result,
    source_filename=source_path.name,
    source_path=str(source_path),
    enrichment=enrichment,    # ← new param, None for audio/captions
)
# SRT and VTT are unchanged — visual content not included in caption files
```

Extend DB recording (step 7) to call `update_history_vision_stats()` when
`enrichment` is not None.

Extend `_write_meta_sidecar()` to include visual fields:

```python
if enrichment:
    meta["scene_count"] = enrichment.total_scenes
    meta["keyframe_count"] = len(enrichment.keyframes)
    meta["frame_descriptions"] = enrichment.described_scenes
    meta["vision_provider"] = enrichment.provider_id
    meta["vision_model"] = enrichment.model
    meta["enrichment_level"] = enrichment.enrichment_level
```

---

## 10. Transcript Formatter Extension

### `core/transcript_formatter.py` (modify)

Extend `to_markdown()` to accept and render visual enrichment data.

**Signature change:**
```python
def to_markdown(
    self,
    result: TranscriptResult,
    source_filename: str,
    source_path: str,
    enrichment: EnrichmentResult | None = None,    # ← new, default None
) -> str:
```

**Frontmatter additions** (when enrichment is not None):
```yaml
scene_count: 12
enrichment_level: 3
vision_provider: ollama
vision_model: llava
```

**Header section addition** (when enrichment is not None):
```markdown
**Duration:** 1:04:07 · **Language:** English · **Engine:** Whisper (local, base)
**Scenes:** 12 · **Vision:** Ollama (llava)
```

**Body — scene-interleaved format** (when enrichment is not None):

Instead of a flat transcript, interleave scene descriptions with transcript
segments. Each scene becomes a section:

```markdown
---

## Scene 1 — 00:00:00–00:02:14

*Visual: Title slide visible — "Q4 2025 Financial Results". Company logo in
upper right corner. No other on-screen graphics.*

[00:00:01] Hello and welcome to the Q4 review. Today we'll be covering
the financial results for the quarter and our outlook for 2026.

[00:00:18] Before we dive in, I want to thank everyone for joining on
short notice this afternoon.

---

## Scene 2 — 00:02:15–00:05:42

*Visual: Bar chart showing quarterly revenue. X-axis: Q1–Q4 2025.
Y-axis: revenue in millions. Q4 bar noticeably taller than prior quarters.*

[00:02:16] So let's look at the numbers. As you can see from this chart...
```

**When description has an error:**
```markdown
## Scene 3 — 00:05:43–00:08:11

*Visual: [frame description unavailable — Ollama unreachable at time of processing]*

[00:05:44] Moving on to operating expenses...
```

**When enrichment is None (audio file or level < 3):**
Use the existing flat transcript format from v0.8.0. No changes to that path.

**Segment-to-scene assignment:**
A transcript segment belongs to the scene where `scene.start_seconds <=
segment.start <= scene.end_seconds`. Assign unmatched segments to the nearest scene.
Never drop a segment.

---

## 11. Search Indexer Extension

### `core/search_indexer.py` (modify)

Extend `index_transcript()` to include visual enrichment data in the
`transcripts` index document.

Add fields to the Meilisearch document:
```python
# Visual enrichment fields (null/empty for audio and level < 3)
"frame_descriptions": "<all description texts concatenated, newline separated>",
"scene_count": 12,
"enrichment_level": 3,
"vision_provider": "ollama",
```

Add `frame_descriptions` to `searchableAttributes` in `TRANSCRIPTS_INDEX_SETTINGS`:
```python
"searchableAttributes": [
    "title",
    "content",
    "frame_descriptions",   # ← add this
    "source_filename"
],
```

Add `enrichment_level` to `filterableAttributes`:
```python
"filterableAttributes": [
    # ... existing ...
    "enrichment_level",
    "vision_provider",
],
```

Content of `frame_descriptions` in the index:
- Concatenate all description texts (not error strings) with newlines.
- Strip error entries — `[frame description unavailable...]` text is not useful
  for search.
- Empty string if no descriptions were generated.

---

## 12. Settings API Routes

### `api/routes/settings.py` (new file)

New router. Mount at `/api/settings` in `main.py`. This is separate from
`/api/preferences` (which stays for v0.8.0 preferences — whisper model,
device, engine preference). `/api/settings` handles the new encrypted store.

```
GET /api/settings
    Returns: { "settings": { key: value } }
    Uses get_all_public() — API keys shown as "[set]" or "".
    Includes all keys from SETTINGS_DEFAULTS.

PUT /api/settings
    Body: { "key": "vision.provider", "value": "ollama" }
    Validates key exists in SETTINGS_DEFAULTS.
    Returns 400 for unknown key.
    Returns 422 if value fails type validation (see below).
    Returns: { "key": "...", "updated": true }

PUT /api/settings/bulk
    Body: { "settings": { key: value, ... } }
    Validates all keys first, then writes all.
    Returns: { "updated": ["key1", "key2"], "errors": [] }

GET /api/settings/providers
    Returns static provider metadata + active provider:
    {
      "providers": [
        { "id": "ollama", "display_name": "Ollama (local)",
          "requires_api_key": false, "supports_local": true,
          "default_model": "llava" },
        { "id": "openai", "display_name": "OpenAI (GPT-4o)",
          "requires_api_key": true, "supports_local": false,
          "default_model": "gpt-4o" },
        ...
      ],
      "active": "ollama"
    }

GET /api/settings/providers/{provider_id}/test
    Calls provider.health_check() with 10-second timeout.
    Always returns 200 — check "available" field.
    Returns: { "provider": "ollama", "available": true,
               "message": "Ollama reachable · llava available" }

GET /api/settings/providers/ollama/models
    Calls OllamaVisionProvider.get_available_models().
    Returns: { "models": ["llava", "bakllava", "llava-llama3"] }
    Returns { "models": [] } if Ollama unreachable — never 500.

GET /api/settings/providers/{provider_id}/models
    For non-Ollama providers: returns fixed model list.
    Returns: { "models": ["gpt-4o", "gpt-4o-mini"] }
```

**Validation rules:**
- `vision.provider` must be one of: `ollama`, `openai`, `gemini`, `anthropic`
- `vision.enrichment_level` must be `"1"`, `"2"`, or `"3"`
- `vision.frame_limit` must be integer string, `"1"` to `"200"`
- `vision.enabled`, `vision.save_keyframes` must be `"true"` or `"false"`
- URL keys (`vision.ollama.base_url`) must start with `http://` or `https://`
- `.api_key` keys accept any non-empty string or empty string (to clear the key)

Mount in `main.py`:
```python
from api.routes.settings import router as settings_router
app.include_router(settings_router, prefix="/api/settings")
```

---

## 13. Settings Page Extension

### `static/settings.html` (modify)

Add a **Vision** section after the existing Transcription section.
Keep all existing Transcription controls from v0.8.0 unchanged.

```
Vision & Frame Description
──────────────────────────────────────────────────────────────────
Enable visual frame description   [ ] Off

Enrichment level
  ● 1 — Metadata only (fastest)
  ● 2 — + Transcription only (recommended for audio/most video)
  ● 3 — + Visual frame descriptions  ← only selectable when vision enabled

Frame limit          [ 50 ]   Max scenes per video (1–200)
                              Higher = more detail, more cost/time

Save keyframe images [ ] Off  Stores extracted JPEG frames alongside transcript
                              Useful for debugging. Adds disk usage.

Frame description prompt
  ┌─────────────────────────────────────────────────────────────┐
  │ Describe this frame from a video. Note any visible text,    │
  │ slides, diagrams, charts, people, or on-screen graphics.    │
  │ Be concise and factual. Do not describe what you cannot     │
  │ see clearly.                                                │
  └─────────────────────────────────────────────────────────────┘
  [ Reset to default prompt ]

──────────────────────────────────────────────────────────────────

Vision Provider
  ○ Ollama (local)
      Base URL    [ http://host.docker.internal:11434        ]
      Model       [ llava ▾ ]   ← populated from /api/settings/providers/ollama/models
      [ Test Connection ]       🟢 Ollama reachable · llava available

  ○ OpenAI (GPT-4o)
      API Key     [ ●●●●●●●●●●●●●●●● ]   [ Change ] [ Clear ]
      Model       [ gpt-4o ▾ ]
      [ Test Connection ]       🔴 Not configured
      Cost note:  ~$0.001–0.003 per frame · 50-frame video ≈ $0.05–$0.15

  ○ Google Gemini
      API Key     [ ●●●●●●●●●●●●●●●● ]   [ Change ] [ Clear ]
      Model       [ gemini-1.5-flash ▾ ]
      [ Test Connection ]       🔴 Not configured

  ○ Anthropic (Claude)
      API Key     [ ●●●●●●●●●●●●●●●● ]   [ Change ] [ Clear ]
      Model       [ claude-sonnet-4-6 ▾ ]
      [ Test Connection ]       🔴 Not configured
      Note: Anthropic cannot transcribe audio. This provider is only
            used for frame descriptions, not transcription fallback.
```

**UI behavior:**
- All vision controls disabled (grayed out) when "Enable visual frame description" is off.
- Enrichment level 3 radio button disabled when vision is off.
- Test Connection buttons: call `/api/settings/providers/{id}/test`. Display live
  badge (🟢 green / 🔴 red + message). Badge auto-clears after 10 seconds.
- Ollama model dropdown: on page load and after successful test, fetch
  `/api/settings/providers/ollama/models`. If empty, show disabled select
  with "Ollama unreachable" placeholder.
- API key fields: `type="password"`. Show/hide toggle (eye icon, pure CSS/JS).
  On blur with non-empty non-`[set]` value: call `PUT /api/settings` to save.
  Show ✓ badge for 3 seconds.
  "Change" button: clears input for re-entry. "Clear" button: sets key to `""`.
- API key display: if API returns `"[set]"`, render as placeholder `••••••••••••••••`
  with "Change" and "Clear" buttons instead of an editable field.
- All settings auto-save on change (same pattern as Transcription section).

### New preferences in `_PREFERENCE_SCHEMA`

These are non-sensitive vision settings (no encryption needed — use existing
preferences system):

| Key | Type | Default | Options | Label |
|-----|------|---------|---------|-------|
| `vision_enrichment_level` | select | `2` | 1/2/3 | Enrichment level |
| `vision_frame_limit` | int | `50` | 1–200 | Max frames per video |
| `vision_save_keyframes` | toggle | `false` | | Save keyframe images |

Sensitive settings (provider, API keys, base URL, model, prompt) live in the
`settings` table via `SettingsManager`. Do NOT add API keys to `_PREFERENCE_SCHEMA`.

---

## 14. History Page Extension

### `static/history.html` (modify)

Extend the inline detail panel for video files to show enrichment info.

**Detail panel additions** (video files only):

```
🎬 Q4_Meeting.mp4
  Transcribed: 2026-03-21 14:32:01
  Duration: 1:04:07 · Language: English
  Engine: Whisper (local, base model)
  Words: 8,432 · Segments: 412
  Scenes: 12 · Enrichment: Level 3 · Vision: Ollama (llava)
  Descriptions: 12/12 successful
  Output: Q4_Meeting.md · Q4_Meeting.srt · Q4_Meeting.vtt
  [Download MD]  [Download SRT]  [Download VTT]
```

If vision failed for some frames:
```
  Descriptions: 9/12 (3 failed — Ollama unreachable)
```

---

## 15. Debug Dashboard Extension

### `static/debug.html` (modify)

Extend debug activity section:

```
Vision stats today:  Scenes detected: 156 · Frames described: 143 · Failed: 13
Provider: Ollama (llava) · Avg time/frame: 4.2s
```

Extend `/debug/api/activity` response:

```json
"vision_stats": {
    "scenes_detected_today": 156,
    "frames_described_today": 143,
    "frames_failed_today": 13,
    "active_provider": "ollama",
    "active_model": "llava",
    "avg_seconds_per_frame": 4.2
}
```

---

## 16. Tests

### `tests/test_scene_detector.py` (new)

- [ ] `detect()` returns at least 1 scene for a valid video
- [ ] Single-scene fallback when 0 scenes detected
- [ ] `frame_limit=3` caps scenes to 3 even when more detected
- [ ] First and last scenes preserved when downsampling
- [ ] `midpoint_seconds` falls between `start_seconds` and `end_seconds`
- [ ] PySceneDetect exception → returns single-scene fallback, does not raise
- [ ] Duration 0 video → returns single-scene fallback

### `tests/test_keyframe_extractor.py` (new)

- [ ] Extracts one JPEG per scene for a test video (use ffmpeg-generated fixture)
- [ ] Output files named `scene_000.jpg`, `scene_001.jpg`, etc.
- [ ] Failed extraction sets `extraction_error`, does not raise
- [ ] `output_dir` provided → files copied to persistent location
- [ ] `output_dir` None → files stay in tmp only
- [ ] Concurrency: 4 scenes extracted concurrently (mock semaphore to verify)

**Test fixtures** — add to `conftest.py` (or reuse v0.8.0 fixtures if present):
```python
@pytest.fixture(scope="session")
def test_mp4(tmp_path_factory):
    """3-second black MP4 with 1 audio track."""
    path = tmp_path_factory.mktemp("media") / "test.mp4"
    subprocess.run([
        "ffmpeg",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "3", "-c:v", "libx264", "-c:a", "aac",
        str(path), "-y"
    ], check=True, capture_output=True)
    return path
```

### `tests/test_vision_providers.py` (new)

All tests mock HTTP calls — no real API calls in CI.

- [ ] `OllamaVisionProvider.health_check()` — mock unreachable → `(False, ...)`
- [ ] `OllamaVisionProvider.health_check()` — mock model missing → `(True, ...)` with warning
- [ ] `OllamaVisionProvider.describe_frame()` — mock success → description text returned
- [ ] `OllamaVisionProvider.describe_frame()` — mock 500 → `FrameDescription(error=...)`
- [ ] `OllamaVisionProvider.describe_frame()` — connection error → graceful, does not raise
- [ ] `OllamaVisionProvider.get_available_models()` — mock tags response → filters vision models
- [ ] `OpenAIVisionProvider.health_check()` — mock 401 → `(False, "Invalid API key")`
- [ ] `OpenAIVisionProvider.health_check()` — mock 200 → `(True, ...)`
- [ ] `OpenAIVisionProvider.describe_frame()` — mock success → correct request format sent
- [ ] `OpenAIVisionProvider.describe_frame()` — mock timeout → graceful error
- [ ] `GeminiVisionProvider.describe_frame()` — mock success → response parsed correctly
- [ ] `GeminiVisionProvider.describe_frame()` — mock 403 → graceful error
- [ ] `AnthropicVisionProvider.describe_frame()` — mock success → content[0].text extracted
- [ ] `AnthropicVisionProvider.health_check()` — mock 429 → `(True, "reachable (rate limited)")`
- [ ] Provider registry: `get_provider("none")` → None
- [ ] Provider registry: `get_provider("unknown")` → None
- [ ] Provider registry: `get_provider("ollama")` → OllamaVisionProvider instance

### `tests/test_settings_manager.py` (new)

- [ ] `get()` returns default for unset key
- [ ] `get()` returns decrypted value after `set()` with API key
- [ ] `set()` raises `ValueError` for unknown key
- [ ] `get_all_public()` returns `"[set]"` for non-empty API key, not ciphertext
- [ ] `get_all_public()` returns `""` for empty API key
- [ ] Stored value is NOT plaintext after `set()` with API key (ciphertext in DB)
- [ ] `set_many()` validates all keys before writing
- [ ] `reset_to_defaults()` clears all rows (next `get()` returns default)
- [ ] Auto-generates key file when `MARKFLOW_SECRET_KEY` not set and file missing
- [ ] Uses env var key when `MARKFLOW_SECRET_KEY` is set
- [ ] Decryption failure on corrupted value → returns `""`, does not raise

### `tests/test_visual_enrichment_engine.py` (new)

- [ ] Enrichment level 2 → scenes and keyframes populated, descriptions empty
- [ ] Enrichment level 3 + provider → `describe_frame()` called for each keyframe
- [ ] Enrichment level 3 + failed keyframe → description has error field, engine continues
- [ ] Provider unreachable → all descriptions have error, result still returned
- [ ] `vision.enabled=false` → no provider calls even at level 3
- [ ] `save_keyframes=false` → no persistent frame files written
- [ ] `save_keyframes=true` → frames copied to `_markflow/frames/`
- [ ] `frame_limit=3` → scene detector capped at 3 (mock SceneDetector)

### `tests/test_transcript_formatter_vision.py` (new)

Extension of the v0.8.0 formatter tests.

- [ ] `to_markdown()` with `enrichment=None` produces identical output to v0.8.0
- [ ] `to_markdown()` with enrichment adds `## Scene N —` headers
- [ ] Scene headers include correct start/end timestamps
- [ ] `*Visual:*` line appears under each scene header when description available
- [ ] `*Visual: [frame description unavailable...]*` appears when error set
- [ ] Transcript segments correctly assigned to their scene
- [ ] Segments not between any scene boundary assigned to nearest scene (never dropped)
- [ ] Frontmatter includes `scene_count`, `enrichment_level`, `vision_provider`
- [ ] `to_srt()` output identical with or without enrichment (captions unchanged)
- [ ] `to_vtt()` output identical with or without enrichment (captions unchanged)

### `tests/test_settings_api.py` (new)

- [ ] `GET /api/settings` returns all default keys
- [ ] `GET /api/settings` API key values are `"[set]"` or `""`
- [ ] `PUT /api/settings` with valid key → 200, value persisted
- [ ] `PUT /api/settings` with unknown key → 400
- [ ] `PUT /api/settings` with invalid value → 422
- [ ] `PUT /api/settings` with API key → stored encrypted, public view shows `"[set]"`
- [ ] `PUT /api/settings/bulk` → all keys updated atomically
- [ ] `GET /api/settings/providers` → returns all 4 providers + active
- [ ] `GET /api/settings/providers/ollama/test` → 200 with `available` field
- [ ] `GET /api/settings/providers/ollama/models` → 200 with `models` list
- [ ] `GET /api/settings/providers/openai/models` → returns fixed list, no API call

---

## 17. Done Criteria

- [ ] Track A (Settings): `settings` table created, `SettingsManager` encrypts/decrypts correctly
- [ ] Track B (Scene detection): `SceneDetector` produces scene boundaries for test video
- [ ] Track C (Keyframes): `KeyframeExtractor` produces one JPEG per scene
- [ ] Track D (Vision providers): All 4 providers implement describe_frame() with graceful failure
- [ ] Track E (Enrichment engine): Level 2 = no vision calls; Level 3 = provider called per frame
- [ ] Track F (Formatter): Video transcripts interleave scene headers + descriptions with segments
- [ ] Track G (Search): `frame_descriptions` field indexed in Meilisearch `transcripts` index
- [ ] Track H (Settings API): `/api/settings` CRUD works; provider test/models endpoints work
- [ ] Track I (Settings UI): Vision section renders, provider selector works, test buttons live
- [ ] Track J (History): Video detail panel shows scene count + enrichment level
- [ ] Audio files unchanged: no scene detection, no vision calls, SRT/VTT unaffected
- [ ] Caption files unchanged: ingest path identical to v0.8.0
- [ ] All v0.8.0 tests still passing
- [ ] New tests: 55+ covering all tracks above
- [ ] `docker-compose up` starts cleanly with `scenedetect` and `cryptography` installed
- [ ] Manual smoke (level 2): upload `.mp4` → transcript with `## Scene N` headers, no vision lines
- [ ] Manual smoke (level 3, Ollama): upload `.mp4` with Ollama running →
      transcript with `*Visual: ...*` lines under each scene header
- [ ] Manual smoke (level 3, Ollama down): Ollama unreachable →
      transcript with `*Visual: [frame description unavailable — ...]*`, no crash
- [ ] API key smoke: enter OpenAI key in settings → stored encrypted, shows `[set]` in UI

---

## 18. CLAUDE.md Update

```markdown
**v0.8.1** — Visual enrichment pipeline. Scene detection (PySceneDetect) and
  keyframe extraction (ffmpeg) for all video files. Optional AI frame descriptions
  via pluggable provider layer: Ollama (local/free), OpenAI GPT-4o, Google Gemini,
  Anthropic Claude Vision. Encrypted API key storage (Fernet) via new settings table
  and SettingsManager. Level 2 enrichment = transcription only (default). Level 3 =
  transcription + scene-interleaved frame descriptions. Audio files, captions, and
  SRT/VTT output unchanged. Settings page Vision section with live provider test.
  55+ new tests.
```

Add to Gotchas:
```markdown
- **SettingsManager vs preferences**: /api/preferences handles non-sensitive
  UI prefs (whisper model, device, engine preference — added in v0.8.0).
  /api/settings handles the new encrypted store (API keys, vision provider,
  base URL, prompt). Never move API keys into _PREFERENCE_SCHEMA.

- **Fernet key rotation**: If MARKFLOW_SECRET_KEY changes after API keys are
  stored, existing encrypted values cannot be decrypted. SettingsManager.get()
  returns "" and logs the error. Users must re-enter their API keys. Document
  this in the settings UI near the API key fields.

- **SceneDetector uses OpenCV**: scenedetect[opencv] installs opencv-python-headless.
  If opencv-python (full GUI) is somehow already present, PySceneDetect uses it —
  do not install both, it causes import conflicts.

- **Frame description is per-scene, not per-segment**: describe_frame() is called
  once per scene (keyframe at midpoint). It is NOT called per transcript segment.
  A scene may contain many segments. The description appears once at the top of
  the scene block in the markdown.

- **Graceful failure contract is absolute**: Every VisionProvider.describe_frame()
  implementation must catch ALL exceptions and return FrameDescription with error
  set. A single provider timeout must never stop a batch. Tests verify this per
  provider.

- **scene_keyframes table history_id**: references conversion_history.id (the
  batch file ID string, same as transcript_segments in v0.8.0). The FK is not
  enforced in SQLite by default — maintain referential integrity in code.

- **SRT and VTT are caption formats only**: Visual frame descriptions are NOT
  included in .srt or .vtt output files. These formats are for subtitles only.
  The full scene+description content is only in the .md file and the search index.
```

Tag: `git tag v0.8.1 && git push origin v0.8.1`

---

## 19. Turn Breakdown

Large changeset — 7 turns recommended:

1. **Turn 1**: DB schema (`settings`, `scene_keyframes` tables, new columns,
   new helpers), `core/settings_manager.py`, `tests/test_settings_manager.py`

2. **Turn 2**: `core/vision_providers/` package (base, all 4 providers, registry),
   `tests/test_vision_providers.py`

3. **Turn 3**: `core/scene_detector.py`, `core/keyframe_extractor.py`,
   `tests/test_scene_detector.py`, `tests/test_keyframe_extractor.py`

4. **Turn 4**: `core/visual_enrichment_engine.py`,
   extend `core/media_orchestrator.py`,
   extend `core/transcript_formatter.py`,
   `tests/test_visual_enrichment_engine.py`,
   `tests/test_transcript_formatter_vision.py`

5. **Turn 5**: `api/routes/settings.py`, mount in `main.py`,
   extend `core/search_indexer.py` (frame_descriptions field),
   `tests/test_settings_api.py`

6. **Turn 6**: `static/settings.html` Vision section,
   `static/history.html` detail panel extension,
   `static/debug.html` vision stats

7. **Turn 7**: Full test suite run, fix failures, CLAUDE.md update, tag v0.8.1
