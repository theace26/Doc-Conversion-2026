# MarkFlow — Logging Settings Feature Prompt

## Context

Read `CLAUDE.md` for full project context. This prompt adds a configurable logging
level system to MarkFlow with a Settings UI section, dynamic level switching at runtime,
and a dual-file logging strategy.

**Current state**: `core/logging_config.py` configures structlog JSON logging with a
single rotating file handler writing to `logs/markflow.log`. Log level is static
(set at startup from `DEBUG` env var). There is no user-facing log level control.

**Target version**: v0.9.5

---

## What to Build

### 1. Logging Level Preference

Add `log_level` to the preferences schema in `core/database.py`.

```python
"log_level": {
    "default": "normal",
    "type": "str",
    "enum": ["normal", "elevated", "developer"],
    "description": "Logging verbosity: normal (WARNING+), elevated (INFO+), developer (DEBUG + frontend trace)"
}
```

Add `log_level` to `_SYSTEM_PREF_KEYS` — requires MANAGER role to change (alongside
`worker_count`, `scanner_*`, etc.). This prevents operators from accidentally enabling
developer logging in production.

Map levels to Python logging constants in `core/logging_config.py`:
```python
LEVEL_MAP = {
    "normal": logging.WARNING,
    "elevated": logging.INFO,
    "developer": logging.DEBUG,
}
```

---

### 2. Dual-File Logging Strategy

Rewrite `core/logging_config.py` to support two handlers:

**Handler A — Operational log** (`logs/markflow.log`):
- Always active, regardless of level setting
- Level: `WARNING` when `log_level=normal`, `INFO` when elevated or developer
- Rotation: daily (`when="midnight"`), keep 30 days (`backupCount=30`)
- Format: structlog JSON with `timestamp`, `level`, `event`, `logger`, request_id, duration_ms

**Handler B — Debug trace log** (`logs/markflow-debug.log`):
- Only active when `log_level=developer`
- Level: `DEBUG` — captures everything including frontend client events
- Rotation: daily, keep 7 days (`backupCount=7`)
- Same structlog JSON format

Timestamp format for both files: ISO 8601 with timezone offset.
Example: `"timestamp": "2026-03-25T14:32:07.341-07:00"`

Both files must be created under the `logs/` directory (mapped to `./logs` on the host
via docker-compose volume). Ensure the directory is created with `os.makedirs(logs_dir, exist_ok=True)`
before attaching handlers.

**`configure_logging(level: str = "normal")` function signature** — called once at
startup in `main.py` lifespan, passing the value from the preferences table:

```python
pref_level = await get_preference("log_level")  # read from DB
configure_logging(level=pref_level or "normal")
```

---

### 3. Dynamic Level Switching (No Restart Required)

Add a function to `core/logging_config.py`:

```python
def update_log_level(new_level: str) -> None:
    """Hot-swap the active log level. Called when the preference is saved."""
    ...
```

This function:
1. Resolves `new_level` string → Python logging constant via `LEVEL_MAP`
2. Updates `logging.root` level
3. Updates Handler A's level (WARNING or INFO based on new_level)
4. Adds or removes Handler B (debug trace): add if `new_level == "developer"`, remove otherwise
5. Logs a WARNING-level event: `"Log level changed"` with `old_level` and `new_level` fields
   so the change is always visible in the operational log regardless of previous level

Hook this into `api/routes/preferences.py`: when `key == "log_level"`, call
`update_log_level(value)` after the DB write succeeds.

---

### 4. Frontend Client Event Logging (Developer Mode Only)

Add a new lightweight endpoint for the JavaScript front end to emit trace events:

**`POST /api/log/client-event`** — no auth required in dev bypass mode, requires
`search_user` role minimum otherwise.

Request body (JSON):
```json
{
  "page": "bulk.html",
  "event": "click",
  "target": "btn-start-job",
  "detail": "optional extra context string"
}
```

Behavior:
- If `log_level != "developer"`, return `204 No Content` immediately (no-op, no log write)
- If `log_level == "developer"`, log at `DEBUG` level with structured fields:
  `"event": "client_action"`, `page`, `event_type`, `target`, `detail`
- Never returns an error to the client — silently swallow all exceptions internally
- Rate limit: max 50 events/second per IP to prevent runaway JS loops filling disk
  (use a simple module-level `defaultdict(deque)` token bucket, no Redis required)

Add the router to `main.py` as `/api/log`.

**Instrument the frontend JS** (`static/js/app.js`):

Add a helper function:
```javascript
async function logClientEvent(event, target, detail = "") {
  if (!window._devLoggingEnabled) return;   // gate on flag set by /api/preferences check
  try {
    await fetch("/api/log/client-event", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ page: location.pathname, event, target, detail })
    });
  } catch { /* never throw */ }
}
```

On page load, `app.js` already fetches `/api/preferences` to read settings. Add:
```javascript
window._devLoggingEnabled = (prefs.log_level === "developer");
```

Instrument these specific actions in `app.js` and inline `<script>` blocks across pages:
- Navigation link clicks (all nav items)
- Form submissions (`POST /api/bulk/jobs` start, `POST /api/convert`)
- Bulk job pause/resume/cancel button clicks
- Settings save button
- Log level change itself

Do NOT instrument every mouse event, scroll, or input keypress — only meaningful user
actions and state transitions. Quantity target: ~15–20 instrumented events total across
the app. Developer mode should give useful trace output without becoming noise.

---

### 5. Settings UI — Logging Section

Add a **Logging** section to `static/settings.html` between the existing OCR section
and the LLM Providers section.

Section layout:

```
┌─ Logging ──────────────────────────────────────────────────┐
│                                                              │
│  Log Level           [Normal ▼]  (requires Manager role)    │
│                                                              │
│  Normal     — Errors, crashes, warnings only                 │
│  Elevated   — + files being processed, job events           │
│  Developer  — Everything: DEBUG + frontend action trace      │
│                                                              │
│  Log files:                                                  │
│   • Operational:  /app/logs/markflow.log    (always active)  │
│   • Debug trace:  /app/logs/markflow-debug.log (dev mode)    │
│                                                              │
│  [Download markflow.log]  [Download markflow-debug.log]      │
│                                                              │
│  ⚠ Developer logging writes every user action to disk.      │
│    Disable when not actively debugging.                      │
└──────────────────────────────────────────────────────────────┘
```

Implementation details:
- Dropdown (`<select>`) for level selection, styled with the existing form CSS
- If user role is below MANAGER, the dropdown is `disabled` with a tooltip:
  "Requires Manager role"
- On change: `PUT /api/preferences/log_level` with new value
- Show success/error toast using the existing toast system from `app.js`
- The two download buttons call new endpoints (see §6 below)
- Warning banner for developer mode uses the existing `.alert-warning` CSS class

---

### 6. Log File Download Endpoints

Add to a new file `api/routes/logs.py`:

**`GET /api/logs/download/{filename}`** where `filename` is `markflow.log` or
`markflow-debug.log` (whitelist — reject anything else with 400).

- Requires MANAGER role
- Returns the file as `application/octet-stream` with `Content-Disposition: attachment`
- If the file does not exist, return 404 with `{"detail": "Log file not found"}`
- Stream the file with `FileResponse` (FastAPI built-in) — do not load into memory

Register router in `main.py` at `/api/logs`.

---

### 7. Add to `_PREFERENCE_SCHEMA` in `core/database.py`

```python
"log_level": {
    "default": "normal",
    "type": "str",
    "enum": ["normal", "elevated", "developer"],
    "description": "Logging verbosity level"
},
```

Ensure `validate_preference_value()` checks the enum on write and rejects unknown values.

---

## Files to Create

| File | Action |
|------|--------|
| `api/routes/logs.py` | New — log download endpoints |
| `api/routes/client_log.py` | New — POST /api/log/client-event |

## Files to Modify

| File | What Changes |
|------|-------------|
| `core/logging_config.py` | Dual-file handlers, `configure_logging(level)`, `update_log_level(level)` |
| `core/database.py` | Add `log_level` to `_PREFERENCE_SCHEMA`, add to `_SYSTEM_PREF_KEYS` |
| `api/routes/preferences.py` | Hook `update_log_level()` on `log_level` key write |
| `main.py` | Read `log_level` pref at startup, pass to `configure_logging()`, register new routers |
| `static/settings.html` | Add Logging section (§5 layout above) |
| `static/js/app.js` | Add `logClientEvent()`, set `window._devLoggingEnabled`, instrument ~15 actions |

---

## Test Requirements

Add `tests/test_logging.py`:

```python
# Test: configure_logging("normal") sets root level to WARNING
# Test: configure_logging("elevated") sets root level to INFO
# Test: configure_logging("developer") sets root level to DEBUG and creates debug handler
# Test: update_log_level("developer") from "normal" adds debug handler
# Test: update_log_level("normal") from "developer" removes debug handler
# Test: POST /api/log/client-event with dev mode off returns 204 and does NOT log
# Test: POST /api/log/client-event with dev mode on returns 204 and logs to debug handler
# Test: POST /api/log/client-event with malformed body returns 204 (never errors)
# Test: GET /api/logs/download/markflow.log returns file as attachment (manager role)
# Test: GET /api/logs/download/markflow.log returns 403 for search_user role
# Test: GET /api/logs/download/../../etc/passwd returns 400 (path traversal blocked)
# Test: GET /api/logs/download/unknown.log returns 400 (not in whitelist)
# Test: PUT /api/preferences/log_level with operator role returns 403
# Test: update_log_level() change event is always visible in operational log
```

Add integration test: set level to `elevated`, trigger a bulk conversion event,
assert INFO-level conversion event appears in `logs/markflow.log`.

---

## Done Criteria

- [ ] `log_level` preference exists in DB schema with enum validation
- [ ] `configure_logging("normal")` writes only WARNING+ to `logs/markflow.log`
- [ ] `configure_logging("elevated")` writes INFO+ to `logs/markflow.log`
- [ ] `configure_logging("developer")` writes INFO+ to `logs/markflow.log` AND DEBUG to `logs/markflow-debug.log`
- [ ] Changing level in Settings updates logging immediately (no restart required)
- [ ] Level change event is always written to `logs/markflow.log` regardless of previous level
- [ ] `POST /api/log/client-event` is a no-op unless `log_level=developer`
- [ ] Nav clicks, job starts, and settings saves are instrumented in JS
- [ ] Settings UI Logging section renders correctly; dropdown disabled for non-manager roles
- [ ] Download buttons on Settings page return log files correctly
- [ ] Path traversal on download endpoint is rejected
- [ ] All new tests pass; total test count increases by at least 12
- [ ] `CLAUDE.md` updated, version tagged v0.9.5

---

## CLAUDE.md Update

After completing the above, append to the Current Status section:

```
**v0.9.5** — Configurable logging levels with dual-file strategy. Three levels:
  Normal (WARNING+), Elevated (INFO+), Developer (DEBUG + frontend trace).
  Operational log always active (logs/markflow.log, 30-day rotation).
  Debug trace log (logs/markflow-debug.log, 7-day) only active in Developer mode.
  Dynamic level switching — no container restart required. Settings UI Logging section
  with log file downloads. POST /api/log/client-event instruments ~15 JS actions in
  Developer mode (rate-limited, silently dropped at other levels).
  log_level is a system-level preference requiring Manager role.
```

Tag: `git tag v0.9.5 -m "Configurable logging levels with dual-file strategy"`
