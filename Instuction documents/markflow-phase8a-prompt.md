# MarkFlow Phase 8a — Settings Infrastructure
## Claude Code Session Prompt

Read `CLAUDE.md` before starting. This is Phase 8a of the MarkFlow project (v0.7.3 base).

---

## Pre-Flight Checks

Before writing any code:
1. Confirm the path safety patch and active files patch have both landed.
2. Run `pytest -q` — all 496 tests must pass before you touch anything.
3. If tests fail, stop and report. Do not proceed.

---

## Objective

Build the settings infrastructure that Phase 8b–8d will build on top of. This session
does NOT add any media handling — it only establishes:

- A `settings` table in SQLite
- A `SettingsManager` core class (typed get/set, defaults, encryption for API keys)
- `/api/settings` REST endpoints
- An updated Settings page in the UI with tabs including the new Media and Providers tabs
  (UI shells only — no functional provider controls yet, those come in 8b)

---

## Files to Create

### 1. `app/core/settings_manager.py`

A typed key-value settings manager backed by the SQLite `settings` table.

```python
# Interface — implement this fully
class SettingsManager:
    DEFAULTS: dict[str, str]  # all defaults as strings
    
    async def get(self, key: str) -> str
    async def get_bool(self, key: str) -> bool
    async def get_int(self, key: str) -> int
    async def set(self, key: str, value: str) -> None
    async def set_many(self, updates: dict[str, str]) -> None
    async def get_all(self) -> dict[str, str]
    async def get_all_public(self) -> dict[str, str]  # excludes encrypted keys
    async def reset_to_defaults(self) -> None
```

**Encryption rules:**
- Keys ending in `.api_key` are encrypted at rest using `cryptography.fernet`.
- Fernet key source (in order of preference):
  1. `MARKFLOW_SECRET_KEY` environment variable (base64url-encoded 32-byte key)
  2. `app/data/secret.key` file — auto-generated on first boot if missing
- `get_all_public()` returns `"[set]"` for any key ending in `.api_key` that has a
  non-empty value, and `""` for unset keys. The raw encrypted value is NEVER returned
  to the API caller.
- A separate internal `get_secret(key)` method returns the decrypted value for use
  by provider classes only. This method is not exposed via the API.

**Defaults** (define as a class-level dict, all values as strings):
```python
DEFAULTS = {
    # Vision provider
    "vision.provider": "none",
    "vision.enabled": "false",
    "vision.ollama.base_url": "http://host.docker.internal:11434",
    "vision.ollama.model": "llava",
    "vision.claude.api_key": "",
    "vision.openai.api_key": "",
    "vision.gemini.api_key": "",
    "vision.frame_prompt": (
        "Describe this frame from a document or presentation. "
        "Note any visible text, charts, diagrams, logos, or graphics. "
        "Be concise and factual."
    ),
    # Transcription
    "transcription.whisper_model": "base",
    "transcription.language": "auto",
    "transcription.enrichment_level": "2",
    # Search indexing
    "search.index_media": "true",
    "search.index_adobe": "true",
    "search.index_media_transcripts": "true",
    "search.index_media_frame_descriptions": "true",
}
```

Use `aiosqlite` for all DB access (same pattern as existing `db.py`).

---

### 2. DB Migration — `app/core/db.py`

Add the following to `_create_tables()` (or a new `_run_migrations()` function if
you introduce one). This must be idempotent — use `CREATE TABLE IF NOT EXISTS`.

```sql
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS media_transcriptions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash        TEXT NOT NULL UNIQUE,
    source_path      TEXT NOT NULL,
    media_type       TEXT NOT NULL,
    duration_secs    REAL,
    codec            TEXT,
    container        TEXT,
    enrichment_level INTEGER NOT NULL DEFAULT 2,
    vision_provider  TEXT,
    transcript_path  TEXT,
    sidecar_path     TEXT,
    word_count       INTEGER,
    segment_count    INTEGER,
    scene_count      INTEGER,
    status           TEXT NOT NULL DEFAULT 'pending',
    error_message    TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### 3. `app/api/routes/settings.py`

New router. Mount at `/api/settings` in `main.py`.

**Endpoints:**

```
GET  /api/settings
     Returns: { "settings": { key: value, ... } }
     Uses get_all_public() — API keys returned as "[set]" or "".
     
PUT  /api/settings
     Body: { "key": "vision.provider", "value": "ollama" }
     Validates key exists in DEFAULTS. Returns 400 for unknown keys.
     Returns 422 if value fails type validation.
     Returns: { "key": ..., "updated": true }

PUT  /api/settings/bulk
     Body: { "settings": { key: value, ... } }
     Applies all at once via set_many(). Returns list of results.
     
POST /api/settings/reset
     Resets all settings to defaults.
     Returns: { "reset": true }

GET  /api/settings/providers
     Returns the static list of all known vision providers with their metadata.
     Does NOT do live health checks (that's the /test endpoint in 8b).
     Format:
     {
       "providers": [
         {
           "id": "none",
           "display_name": "None (transcription only)",
           "requires_api_key": false,
           "supports_local": false,
           "available": true
         },
         {
           "id": "ollama",
           "display_name": "Ollama (local)",
           "requires_api_key": false,
           "supports_local": true,
           "available": true    ← always true in this endpoint; live test is separate
         },
         ...
       ],
       "active": "none"   ← current value of vision.provider setting
     }
```

**Validation rules:**
- `vision.provider` must be one of: `none`, `ollama`, `claude`, `openai`, `gemini`
- `transcription.whisper_model` must be one of: `tiny`, `base`, `small`, `medium`, `large`
- `transcription.enrichment_level` must be `1`, `2`, or `3`
- Boolean keys (`vision.enabled`, `search.index_*`) must be `"true"` or `"false"`
- URL keys (`vision.ollama.base_url`) must start with `http://` or `https://`
- API key keys (`.api_key`) accept any non-empty string or empty string (to clear)

---

### 4. Updated `app/static/settings.html`

Replace the existing settings page with a tabbed layout. Keep all existing preference
controls (they still hit `/api/preferences`). Add new tabs:

**Tab structure:**
```
[ General ] [ Conversion ] [ OCR ] [ Media ] [ Search ] [ API Keys ]
```

The existing preferences (default fidelity tier, batch size, etc.) go under
General/Conversion/OCR tabs. The new tabs:

**Media tab:**
```
Enrichment Level
  ○ 1 — Metadata only (fast, always available)
  ● 2 — + Transcription via Whisper (default)
  ○ 3 — + Visual frame descriptions (requires Vision Provider)

Whisper Model Size
  [ base ▾ ]   tiny / base / small / medium / large
  Note: larger models are more accurate but slower.

Transcription Language
  [ Auto-detect ▾ ]   Auto-detect / English / Spanish / French / ...
```

**API Keys tab:**
```
Vision Provider
  ○ None (transcription only)
  ○ Ollama (local)
      Base URL: [ http://host.docker.internal:11434 ]
      Model:    [ llava ▾ ]  (dropdown, populated in 8b)
      [ Test Connection ]   ← placeholder button, wired in 8b
  ○ Claude (Anthropic)
      API Key:  [ ●●●●●●●● ] (masked input)
      [ Test Connection ]   ← placeholder
  ○ GPT-4o (OpenAI)
      API Key:  [ ●●●●●●●● ]
      [ Test Connection ]   ← placeholder
  ○ Gemini (Google)
      API Key:  [ ●●●●●●●● ]
      [ Test Connection ]   ← placeholder
```

**Search tab** (consolidate existing search-related preferences here):
```
Index media files in search    ✅
Include transcripts            ✅
Include frame descriptions     ✅
Index Adobe files              ✅
```

Implementation notes:
- Use `markflow.css` variables for all styling — no inline styles.
- Tab switching is pure JS, no page reload.
- API key fields use `type="password"` with a show/hide toggle (eye icon).
- On load, fetch `GET /api/settings` — populate all fields. API keys show as `[set]`
  or empty placeholder.
- On change of any field, call `PUT /api/settings` with the key/value pair.
  Show a small ✓ checkmark next to the field that fades after 2 seconds.
- Test Connection buttons are placeholders in 8a — they show "Coming soon" alert.
  They will be wired in 8b.
- Add a "Reset to defaults" button at the bottom of each tab that resets only that
  tab's settings (call `PUT /api/settings/bulk` with the relevant defaults).

---

## Files to Modify

| File | Change |
|------|--------|
| `app/core/db.py` | Add `settings` and `media_transcriptions` table creation |
| `app/main.py` | Mount new `settings` router |
| `app/static/settings.html` | Tabbed layout with new Media and API Keys tabs |
| `requirements.txt` | Add `cryptography` |

---

## Tests to Write

**`tests/test_settings_manager.py`**
- `test_get_default_value` — unset key returns default
- `test_set_and_get` — set a value, get it back
- `test_set_many` — bulk update, all values persisted
- `test_api_key_encrypted_at_rest` — after setting an API key, the raw DB value
  is not the plaintext key (i.e., it's ciphertext)
- `test_get_all_public_masks_api_keys` — API keys appear as `"[set]"` not plaintext
- `test_reset_to_defaults` — after reset, all keys return defaults
- `test_unknown_key_ignored` — setting an unknown key does not raise, or raises
  cleanly (decide which and document it — recommend raising `ValueError`)

**`tests/test_settings_api.py`**
- `test_get_settings` — GET /api/settings returns expected structure
- `test_put_settings_valid` — update a valid key
- `test_put_settings_invalid_key` — 400 for unknown key
- `test_put_settings_invalid_value` — 422 for bad value (e.g. provider="nonexistent")
- `test_put_settings_api_key` — setting an API key, verify public view shows "[set]"
- `test_reset_settings` — POST /api/settings/reset restores defaults
- `test_get_providers` — returns list with "none" + "ollama" + 3 cloud providers

---

## Done Criteria

- [ ] `settings` and `media_transcriptions` tables created on startup
- [ ] `SettingsManager.get()` returns defaults for unset keys
- [ ] API key values encrypted in DB, masked in API responses
- [ ] `GET /api/settings` returns public settings dict
- [ ] `PUT /api/settings` updates a key with validation
- [ ] `GET /api/settings/providers` returns provider list
- [ ] Settings page shows tabs (General, Conversion, OCR, Media, Search, API Keys)
- [ ] Media tab controls read from and write to `/api/settings`
- [ ] API Keys tab shows provider selector with masked key inputs
- [ ] All 496 pre-existing tests still pass
- [ ] New settings tests all pass
- [ ] `docker-compose build && docker-compose up -d` clean
- [ ] CLAUDE.md updated with v0.8.0 status
- [ ] Tag: `git tag v0.8.0 && git push --tags`
