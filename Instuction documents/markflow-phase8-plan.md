# MarkFlow Phase 8 — Media & Audio Transcription
## Planning Document

**Builds on:** v0.7.3 (Phases 0–7 complete)  
**Goal:** Add media file indexing (video + audio) with a provider abstraction layer so
the user can choose between Ollama (local), Claude, OpenAI, or Gemini for visual frame
description — all configurable from the Settings page.

---

## ⚠️ Pre-Flight Checklist

Before starting Phase 8a, confirm both queued patches have landed:
- [ ] Path safety patch applied and tested
- [ ] Active files patch applied and tested
- [ ] `docker-compose build && docker-compose up -d` clean after patches
- [ ] All 496 existing tests still pass

Do not begin Phase 8a until these are checked off.

---

## What Phase 8 Adds

### New Supported Input Formats

**Video:**
- `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.wmv`, `.flv`

**Audio:**
- `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.aac`, `.wma`, `.opus`

All format/codec/wrapper detection is **fully automatic** — the end user never
chooses a codec. ffprobe interrogates every file at ingest time and selects the
correct decode path. If a format needs transcoding before Whisper, ffmpeg handles
it silently in a temp directory.

### New Output Per File

For `quarterly-review.mp4`:
```
quarterly-review.md              ← full structured transcript
quarterly-review.media.json      ← metadata sidecar (duration, codec, resolution, etc.)
quarterly-review.frames/         ← keyframe images (optional, Level 3 only)
```

For `team-voicemail.mp3`:
```
team-voicemail.md                ← transcript with timestamps
team-voicemail.media.json        ← metadata sidecar (duration, codec, bitrate, etc.)
```

### Vision Provider Options

| Provider ID   | Type   | Cost      | Quality   | Available |
|---------------|--------|-----------|-----------|-----------|
| `none`        | —      | Free      | —         | Always    |
| `ollama`      | Local  | Free      | Good      | If running|
| `claude`      | API    | Per-frame | Best      | API key   |
| `openai`      | API    | Per-frame | Very good | API key   |
| `gemini`      | API    | Per-frame | Very good | API key   |

### Enrichment Levels (consistent with Adobe levels in Phase 7)

- **Level 1** — Metadata only. Duration, codec, resolution, bitrate, creation date.
  Runs always. Near-instant.
- **Level 2** — + Whisper transcription. Timestamped text segments. Free, local.
  Takes ~0.25× realtime on CPU (faster on GPU).
- **Level 3** — + Visual frame descriptions. Scene detection → keyframe extraction →
  provider API/local call per scene. Opt-in. Costs API credits or GPU time.

---

## Session Breakdown

| Session | Scope                                       | Est. Files Changed |
|---------|---------------------------------------------|--------------------|
| **8a**  | Settings infrastructure (DB, API, UI)       | 8–12               |
| **8b**  | Provider abstraction + Ollama + Whisper     | 10–14              |
| **8c**  | MediaHandler + AudioHandler (core pipeline) | 8–12               |
| **8d**  | Cloud providers + Meilisearch + search UI   | 8–10               |

Run sessions in order. Each session ends with: all existing tests pass + new tests
for that session pass + CLAUDE.md updated + version tagged.

---

## New DB Schema (added in 8a)

```sql
-- Key-value settings store
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'string',  -- string, int, bool, json
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Media file transcription records
CREATE TABLE media_transcriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash       TEXT NOT NULL UNIQUE,
    source_path     TEXT NOT NULL,
    media_type      TEXT NOT NULL,  -- 'video' or 'audio'
    duration_secs   REAL,
    codec           TEXT,
    container       TEXT,
    enrichment_level INTEGER NOT NULL DEFAULT 2,
    vision_provider TEXT,
    transcript_path TEXT,
    sidecar_path    TEXT,
    word_count      INTEGER,
    segment_count   INTEGER,
    scene_count     INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## New Directory Structure

```
app/
├── providers/
│   ├── __init__.py
│   ├── vision_base.py          ← Abstract VisionProvider
│   ├── vision_registry.py      ← maps provider_id → class
│   ├── vision_ollama.py        ← Ollama/LLaVA
│   ├── vision_claude.py        ← Anthropic Claude Vision
│   ├── vision_openai.py        ← OpenAI GPT-4o Vision
│   ├── vision_gemini.py        ← Google Gemini Vision
│   ├── transcription_base.py   ← Abstract TranscriptionProvider
│   ├── transcription_registry.py
│   └── transcription_whisper.py ← OpenAI Whisper (local)
├── formats/
│   ├── media_handler.py        ← video files
│   └── audio_handler.py        ← audio-only files
├── core/
│   ├── settings_manager.py     ← typed get/set with defaults
│   └── media_probe.py          ← ffprobe wrapper, auto-detects all formats
├── api/routes/
│   └── settings.py             ← /api/settings endpoints (replaces /api/preferences
│                                  for new settings; preferences stays for legacy)
└── static/
    ├── settings.html           ← updated with Media & Providers tabs
    └── css/markflow.css        ← minor additions for provider status badges
```

---

## Architecture Rules (carry-forward + new)

All existing rules from CLAUDE.md apply. New rules for Phase 8:

- **No hardcoded codecs** — `media_probe.py` always uses ffprobe output to select
  decode path. Never branch on file extension for codec logic.
- **Temp files in /tmp** — All ffmpeg intermediate files go to a unique temp dir
  that is cleaned up in a `finally` block. Never write intermediates to the source
  share or the output repo.
- **Whisper model cached** — Load the Whisper model once at startup (or on first
  use) and cache the instance. Don't reload per file.
- **Vision calls are optional** — If the vision provider is unreachable at
  conversion time, the handler logs the error, marks that scene as
  `[vision unavailable — {provider} unreachable]` in the transcript, and continues.
  One failed API call never stops a batch.
- **API keys encrypted at rest** — Use `cryptography.fernet`. Derive the Fernet key
  from a machine secret (generate on first boot, store in `MARKFLOW_SECRET_KEY` env
  var or auto-generate and persist to `app/data/secret.key`). Never store raw key
  values in the settings table or logs.
- **Settings API is separate from Preferences API** — `/api/preferences` stays for
  backward compat (Phase 6 items). `/api/settings` is the new endpoint for Phase 8+
  settings. Both read from the same `settings` table via `SettingsManager`.

---

## Default Settings Values

```python
SETTINGS_DEFAULTS = {
    # Vision
    "vision.provider": "none",
    "vision.enabled": "false",
    "vision.ollama.base_url": "http://host.docker.internal:11434",
    "vision.ollama.model": "llava",
    "vision.claude.api_key": "",       # encrypted
    "vision.openai.api_key": "",       # encrypted
    "vision.gemini.api_key": "",       # encrypted
    "vision.frame_prompt": (
        "Describe this frame from a document or presentation. "
        "Note: any visible text, charts, diagrams, logos, or graphics. "
        "Be concise and factual."
    ),

    # Transcription
    "transcription.whisper_model": "base",   # tiny/base/small/medium/large
    "transcription.language": "auto",
    "transcription.enrichment_level": "2",   # 1/2/3

    # Search
    "search.index_media": "true",
    "search.index_adobe": "true",
    "search.index_media_transcripts": "true",
    "search.index_media_frame_descriptions": "true",
}
```

---

## Version Tags

| After Session | Tag    | Description                              |
|---------------|--------|------------------------------------------|
| 8a complete   | v0.8.0 | Settings infrastructure                  |
| 8b complete   | v0.8.1 | Provider abstraction + Ollama + Whisper  |
| 8c complete   | v0.8.2 | MediaHandler + AudioHandler              |
| 8d complete   | v0.8.3 | Cloud providers + search integration     |

---

## Done Criteria (Full Phase 8)

- [ ] Upload an `.mp4` → get a `.md` with timestamped transcript + scene headers
- [ ] Upload an `.mp3` → get a `.md` with timestamped transcript
- [ ] Exotic codec (e.g. `.mkv` H.265, `.ogg` Vorbis) auto-detected and handled
- [ ] Settings page shows Media tab with enrichment level + provider selector
- [ ] Ollama test button returns live status (green/red)
- [ ] Switching provider in settings takes effect on next conversion
- [ ] API key fields masked in UI; encrypted in DB
- [ ] Level 3 enrichment adds frame descriptions to transcript
- [ ] Frame description marked `[vision unavailable]` if provider unreachable
- [ ] Media files indexed in Meilisearch; searchable from search UI
- [ ] All 496+ existing tests still pass
- [ ] New tests cover: probe, transcription, handler, settings CRUD, provider health
- [ ] CLAUDE.md updated, v0.8.3 tagged
