# MarkFlow Phase 8c — MediaHandler + AudioHandler
## Claude Code Session Prompt

Read `CLAUDE.md` before starting. This builds on Phase 8b (v0.8.1 base).

---

## Pre-Flight Checks

1. `docker-compose build && docker-compose up -d` — clean start
2. `pytest -q` — all 8a + 8b tests must pass
3. Confirm `WhisperTranscriptionProvider.health_check()` returns `(True, ...)` in the
   running container: `curl localhost:8000/api/settings/providers/transcription/whisper/test`

---

## Objective

Build the two format handlers that process media files into structured Markdown:

- **`AudioHandler`** — audio-only files (`.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`,
  `.aac`, `.wma`, `.opus`)
- **`MediaHandler`** — video files (`.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`,
  `.m4v`, `.wmv`, `.flv`)

Also build **`media_probe.py`** — the ffprobe wrapper that auto-detects every
input file's format, codec, duration, and what pre-processing (if any) is needed
before Whisper. This is the key piece that makes the system transparent to the user.

All three handlers register in the format registry. They plug into the existing
`ConversionOrchestrator` with no changes to its core pipeline logic.

---

## 1. `app/core/media_probe.py`

The single source of truth for "what is this file and how do we handle it."

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class MediaProbeResult:
    # File identity
    path: Path
    container: str          # e.g. "mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm"
    media_type: str         # "video" or "audio"

    # Streams
    has_video: bool
    has_audio: bool
    video_codec: str | None     # e.g. "h264", "hevc", "vp9", "av1"
    audio_codec: str | None     # e.g. "aac", "mp3", "opus", "flac", "pcm_s16le"
    audio_channels: int | None  # 1=mono, 2=stereo, etc.
    audio_sample_rate: int | None  # Hz

    # Duration
    duration_secs: float | None

    # Video geometry (None for audio-only)
    width: int | None
    height: int | None
    frame_rate: float | None    # fps

    # Pre-processing required
    needs_transcode: bool       # True if Whisper can't read this directly
    transcode_args: list[str]   # ffmpeg args to produce a compatible temp file
                                # empty list if no transcode needed

class MediaProbe:
    @staticmethod
    async def probe(path: Path) -> MediaProbeResult:
        """
        Run ffprobe on the file. Parse JSON output.
        Determine needs_transcode and transcode_args.
        Raises MediaProbeError if the file is not a recognized media file.
        """
        ...

    @staticmethod
    async def extract_audio_for_whisper(
        source: Path,
        dest: Path,     # caller provides a temp path ending in .wav or .mp3
        probe: MediaProbeResult,
    ) -> Path:
        """
        If probe.needs_transcode: run ffmpeg to produce a Whisper-compatible file.
        If not: copy or symlink source to dest (for codecs Whisper reads natively).
        Returns the path to use for transcription (may be source or dest).
        All ffmpeg calls use asyncio.to_thread(subprocess.run, ...).
        Timeout: 300 seconds per file.
        """
        ...
```

**Transcode decision logic:**
Whisper can natively read: `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.webm` (opus).
Everything else needs `ffmpeg -i {source} -ac 1 -ar 16000 {dest}.wav`.
For video files, always extract audio-only: `ffmpeg -i {source} -vn -ac 1 -ar 16000 {dest}.wav`.

The rule is: if it's video (has_video=True), always transcode to WAV.
If it's audio and in a natively-supported format, pass through.
If it's audio in an unsupported format (e.g. `.wma`, `.aac`), transcode to WAV.

**ffprobe call:**
```
ffprobe -v quiet -print_format json -show_streams -show_format {path}
```
Parse the JSON. `streams` array contains video/audio stream objects.

**Error handling:**
- `ffprobe` not found → raise `MediaProbeError("ffprobe not found — is ffmpeg installed?")`
- File not recognized (ffprobe returns no streams) → raise `MediaProbeError("Not a recognized media file: {path}")`
- Timeout (30 seconds) → raise `MediaProbeError("ffprobe timed out on {path}")`

---

## 2. `app/formats/audio_handler.py`

```python
SUPPORTED_EXTENSIONS = [
    ".mp3", ".wav", ".m4a", ".flac",
    ".ogg", ".aac", ".wma", ".opus",
]

class AudioHandler(FormatHandler):
    """
    Converts audio files to Markdown transcripts.
    Uses WhisperTranscriptionProvider from the registry.
    """
```

**`ingest(file_path) → DocumentModel` pipeline:**

1. **Probe** — call `MediaProbe.probe(file_path)`. If `MediaProbeError`, re-raise as
   `ConversionError` (same pattern existing handlers use).

2. **Temp dir** — create `tempfile.TemporaryDirectory()`. Use it for all intermediates.
   Always clean up in a `finally` block.

3. **Extract audio** — call `MediaProbe.extract_audio_for_whisper(source, dest, probe)`.
   dest is `tmpdir / f"{file_path.stem}_whisper.wav"`.

4. **Transcribe** — get `WhisperTranscriptionProvider` from registry, call
   `transcribe(audio_path, language=settings.get("transcription.language"))`.

5. **Build DocumentModel**:
   - `metadata.title` = file stem (without extension)
   - `metadata.media_type` = `"audio"`
   - `metadata.duration_secs` = from probe
   - `metadata.codec` = probe.audio_codec
   - `metadata.container` = probe.container
   - `metadata.language` = from transcription result
   - `metadata.word_count` = from transcription result

6. **Add elements**:
   ```
   HEADING (level 1): "{filename} — Audio Transcript"
   PARAGRAPH: "**Duration:** {duration}   **Language:** {language}   **Words:** {word_count}"
   HEADING (level 2): "Transcript"
   ```
   Then for each segment (group into ~30-second blocks if there are many segments):
   ```
   PARAGRAPH: "`[{start} → {end}]` {text}"
   ```
   Format timestamps as `MM:SS` (e.g. `01:23`).

7. **Write sidecar** — `{output_dir}/{stem}.media.json`:
   ```json
   {
     "schema_version": "1.0.0",
     "media_type": "audio",
     "source_file": "{filename}",
     "duration_secs": 125.4,
     "codec": "mp3",
     "container": "mp3",
     "audio_channels": 2,
     "audio_sample_rate": 44100,
     "language": "en",
     "word_count": 342,
     "segment_count": 18,
     "whisper_model": "base",
     "enrichment_level": 2
   }
   ```

8. **Record in DB** — insert into `media_transcriptions` table.

**Export direction:** `export()` raises `NotImplementedError("Audio files cannot be
re-exported from Markdown.")`. Audio is index-only — no round-trip.

---

## 3. `app/formats/media_handler.py`

Same pipeline as AudioHandler, with scene detection and optional vision added.

```python
SUPPORTED_EXTENSIONS = [
    ".mp4", ".mov", ".avi", ".mkv",
    ".webm", ".m4v", ".wmv", ".flv",
]

class MediaHandler(FormatHandler):
    """
    Converts video files to Markdown transcripts with optional scene descriptions.
    Uses WhisperTranscriptionProvider + active VisionProvider from settings.
    """
```

**`ingest(file_path) → DocumentModel` pipeline:**

Steps 1–5 are identical to AudioHandler (probe → temp dir → extract audio → transcribe
→ start building DocumentModel).

Additional steps for video:

**Step 5b — Scene detection** (always runs, regardless of enrichment level):
Use `scenedetect` (PySceneDetect) to find scene boundaries.

```python
from scenedetect import detect, ContentDetector
scenes = detect(str(file_path), ContentDetector())
# scenes is a list of (start_timecode, end_timecode) tuples
```

- If PySceneDetect raises or finds 0 scenes: treat the whole file as one scene.
- Cap at 50 scenes maximum. If more detected, sample evenly down to 50.

**Step 5c — Keyframe extraction** (always runs for video):
For each scene, extract one frame at the midpoint using ffmpeg:
```
ffmpeg -ss {midpoint_sec} -i {source} -frames:v 1 {tmpdir}/scene_{n:03d}.jpg -y
```

**Step 5d — Vision enrichment** (only if `enrichment_level == 3` AND `vision.provider != "none"`):
```python
provider = VisionRegistry.get(settings.get("vision.provider"))
prompt = settings.get("vision.frame_prompt")
for scene_num, frame_path in enumerate(keyframes):
    desc = await provider.describe_frame(frame_path, prompt)
    # desc.error is set if the call failed — insert the error string as-is
```

**Step 6 — Build elements** (video version):
```
HEADING (level 1): "{filename} — Video Transcript"
PARAGRAPH: "**Duration:** {duration}   **Language:** {language}   **Words:** {word_count}   **Scenes:** {scene_count}"
```

For each scene:
```
HEADING (level 2): "Scene {n} — {start_time}–{end_time}"
```
If vision description available:
```
PARAGRAPH: "*Visual:* {description}"
```
Or if vision failed:
```
PARAGRAPH: "*Visual:* [vision unavailable — {error}]"
```
If enrichment_level < 3:
  (no visual line)

Then all transcript segments that fall within this scene's time range:
```
PARAGRAPH: "`[{start} → {end}]` {text}"
```

**Segment-to-scene assignment:**
A transcript segment belongs to the scene whose time range contains `segment.start_sec`.
Segments before any scene → assign to scene 1.
Segments after last scene end → assign to last scene.

**Step 7 — Sidecar** (same as audio but add video fields):
```json
{
  "media_type": "video",
  "width": 1920,
  "height": 1080,
  "frame_rate": 29.97,
  "video_codec": "h264",
  "scene_count": 12,
  "enrichment_level": 3,
  "vision_provider": "ollama"
}
```

**Keyframe images:**
Do NOT copy keyframes to the output directory by default (they can be large).
Only write them if `enrichment_level == 3` AND a setting
`media.save_keyframes` is `"true"` (default `"false"`).
If saved: `{output_dir}/_frames/{stem}/scene_{n:03d}.jpg`

---

## 4. Register Handlers

In `app/formats/__init__.py` (or wherever the format registry is initialized):

```python
from .audio_handler import AudioHandler
from .media_handler import MediaHandler

registry.register(AudioHandler())
registry.register(MediaHandler())
```

---

## 5. Extension Whitelist

In `app/api/routes/convert.py` (or wherever file validation lives), add to the
allowed extension list:
```python
ALLOWED_EXTENSIONS = {
    # ... existing ...
    # Audio
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".opus",
    # Video
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv",
}
```

---

## 6. `requirements.txt` additions

```
scenedetect[opencv]
```

`ffmpeg` is a system dependency — add to the `Dockerfile`:
```dockerfile
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
```

Verify ffmpeg is already in the Dockerfile from the OCR phase (it may be present
for pdf2image). If so, just confirm it's there — don't add a duplicate line.

---

## 7. File Size Limits

The existing upload API enforces a file size limit. Media files are large.
Check the current limit in `convert.py`. Add a new setting:

- `media.max_upload_mb` — default `"500"` (500 MB)

The upload validator should check:
- Non-media files: existing limit (likely 50 MB)
- Media files (audio/video extensions): use `media.max_upload_mb`

---

## Tests to Write

**`tests/test_media_probe.py`**
- `test_probe_mp4` — probe a small test MP4, assert `has_video=True`, `has_audio=True`
- `test_probe_mp3` — probe a small test MP3, assert `media_type="audio"`
- `test_probe_needs_transcode_video` — video file always `needs_transcode=True`
- `test_probe_needs_transcode_wma` — WMA needs transcode
- `test_probe_no_transcode_mp3` — MP3 does not need transcode
- `test_probe_invalid_file` — non-media file raises `MediaProbeError`

**Test fixtures:**
Generate minimal test media files using `ffmpeg` in the fixture setup:
```python
# conftest.py addition
@pytest.fixture(scope="session")
def test_mp3(tmp_path_factory):
    """Generate a 3-second silent MP3 for testing."""
    path = tmp_path_factory.mktemp("media") / "test.mp3"
    subprocess.run([
        "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "3", "-q:a", "9", str(path), "-y"
    ], check=True, capture_output=True)
    return path

@pytest.fixture(scope="session")
def test_mp4(tmp_path_factory):
    """Generate a 3-second silent black MP4 for testing."""
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

**`tests/test_audio_handler.py`**
- `test_audio_handler_mp3` — ingest test MP3, assert DocumentModel has HEADING and PARAGRAPH elements
- `test_audio_handler_produces_sidecar` — sidecar JSON written with correct fields
- `test_audio_handler_records_db` — media_transcriptions row created
- `test_audio_handler_export_raises` — `export()` raises `NotImplementedError`

**`tests/test_media_handler.py`**
- `test_media_handler_mp4` — ingest test MP4, assert HEADING elements include scene headers
- `test_media_handler_sidecar` — sidecar includes `scene_count`, `video_codec`
- `test_media_handler_no_vision_level2` — at enrichment_level 2, no `*Visual:*` lines
- `test_media_handler_vision_unavailable_graceful` — even if vision provider errors,
  handler completes and inserts `[vision unavailable]` text

**`tests/test_convert_api_media.py`**
- `test_upload_mp3_returns_batch` — POST /api/convert with MP3 returns batch_id
- `test_upload_mp4_returns_batch` — same for MP4
- `test_upload_oversized_media_returns_413` — file over limit returns 413

---

## Done Criteria

- [ ] `media_probe.py` correctly identifies audio vs video for all listed extensions
- [ ] Codec/container auto-detected; user never configures this
- [ ] Audio needing transcode is silently converted to WAV in temp dir
- [ ] Temp dirs always cleaned up (verify with a try/finally check)
- [ ] `AudioHandler` ingests `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.aac`, `.wma`, `.opus`
- [ ] `MediaHandler` ingests `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.wmv`, `.flv`
- [ ] Transcript markdown has correct heading structure with timestamps
- [ ] Video transcript groups segments by scene
- [ ] Level 3 enrichment adds `*Visual:*` lines (or graceful unavailable message)
- [ ] Sidecar JSON written for every conversion
- [ ] DB row written in `media_transcriptions` for every conversion
- [ ] File size limit respected (500 MB for media by default)
- [ ] ffmpeg installed in Dockerfile
- [ ] All prior tests still pass
- [ ] New media tests pass
- [ ] CLAUDE.md updated with v0.8.2 status
- [ ] Tag: `git tag v0.8.2 && git push --tags`
