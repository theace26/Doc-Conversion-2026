# MarkFlow Patch: Log Rotation + Settings Download Loop Fix

**Version target:** Bump patch version in CLAUDE.md after applying  
**Scope:** Two bugs — unbounded log file growth + download loop on /settings page  
**Prerequisite:** Read `CLAUDE.md` before touching any file. It is the source of truth.

---

## 0. Context

Two production bugs:

1. **Debug log grows unbounded** — a single `logs/markflow-debug.log` reached 4GB+. No rotation, no size cap. Makes the file impossible to open, parse, or ship to Grafana/Loki.

2. **Settings page download loop** — clicking a download button on `/settings` (likely log download or DB export) downloads the file almost to completion, then restarts from 0% in an infinite loop. The file never finishes. Root cause is almost certainly a missing or incorrect `Content-Length` header combined with frontend `fetch` retry logic that re-triggers on what it interprets as a failed download.

Both fixes go in together because they're related — the download loop is made catastrophic by the unbounded log size.

---

## 1. Fix 1 — Log Rotation

### 1.1 Find the logging configuration

Search for the current log handler setup:

```bash
grep -rn "FileHandler\|addHandler\|logging\.basicConfig\|RotatingFileHandler\|logs/" src/ app/ core/ --include="*.py"
grep -rn "structlog" core/logging_config.py
```

Identify:
- Where log files are opened (likely `core/logging_config.py` or `main.py`)
- Which log files exist (probably `markflow.log` and `markflow-debug.log` at minimum)
- Whether `RotatingFileHandler` is already imported but not used

### 1.2 Apply rotation to ALL file handlers

Replace every `FileHandler` (or `logging.FileHandler`) with `RotatingFileHandler` from `logging.handlers`.

**Settings for each log file:**

| Log File | Max Size | Backup Count | Notes |
|----------|----------|-------------|-------|
| `markflow.log` (INFO+) | 50 MB | 5 | Main application log |
| `markflow-debug.log` (DEBUG) | 100 MB | 3 | Debug log — largest volume |
| Any other `.log` file | 50 MB | 5 | Apply same defaults |

**Implementation:**

```python
from logging.handlers import RotatingFileHandler

# Replace this pattern:
#   handler = logging.FileHandler("logs/markflow-debug.log")
# With this:
handler = RotatingFileHandler(
    "logs/markflow-debug.log",
    maxBytes=100 * 1024 * 1024,  # 100 MB
    backupCount=3,
    encoding="utf-8",
)

# For the main log:
handler = RotatingFileHandler(
    "logs/markflow.log",
    maxBytes=50 * 1024 * 1024,  # 50 MB
    backupCount=5,
    encoding="utf-8",
)
```

### 1.3 Ensure the `logs/` directory exists at startup

In the lifespan or startup code, add:

```python
import os
os.makedirs("logs", exist_ok=True)
```

This may already exist — verify before adding.

### 1.4 Add LOG_MAX_SIZE_MB environment variable (optional but recommended)

Make the max size configurable:

```python
import os
LOG_MAX_SIZE_MB = int(os.environ.get("LOG_MAX_SIZE_MB", "50"))
DEBUG_LOG_MAX_SIZE_MB = int(os.environ.get("DEBUG_LOG_MAX_SIZE_MB", "100"))
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
```

Use these in the handler constructors. Document in `docker-compose.yml` as commented-out env vars.

### 1.5 Verify

After applying:

```bash
# Check that RotatingFileHandler is used everywhere, FileHandler nowhere
grep -rn "FileHandler" core/ app/ src/ --include="*.py" | grep -v "RotatingFileHandler" | grep -v "test_" | grep -v "__pycache__"
```

This should return zero results (excluding test files).

---

## 2. Fix 2 — Settings Download Loop

### 2.1 Find the download endpoint

```bash
grep -rn "download\|send_file\|FileResponse\|StreamingResponse" api/ --include="*.py"
grep -rn "download" static/settings.html static/settings.js static/*.html static/*.js
```

Identify:
- The backend route that serves the file download (likely returns a `FileResponse` or `StreamingResponse`)
- The frontend JS that triggers the download (likely a `fetch()` call or `window.location` redirect)

### 2.2 Backend fix — proper FileResponse headers

The download endpoint MUST use FastAPI's `FileResponse` with explicit headers. If it's using `StreamingResponse` for a file on disk, switch to `FileResponse` — it handles `Content-Length`, `Content-Type`, and range requests automatically.

**Find the download route and ensure it looks like this:**

```python
from fastapi.responses import FileResponse
import os

@router.get("/api/settings/download-logs")  # or whatever the actual path is
async def download_logs():
    log_path = "logs/markflow.log"  # or whatever file is being served
    
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    
    file_size = os.path.getsize(log_path)
    
    # For very large files (>500MB), refuse the download and suggest alternatives
    if file_size > 500 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Log file is {file_size // (1024*1024)}MB — too large to download. "
                   f"Log rotation has been enabled; rotated files will be smaller. "
                   f"Access logs directly in the container at {log_path}"
        )
    
    return FileResponse(
        path=log_path,
        filename=os.path.basename(log_path),
        media_type="application/octet-stream",
        # FileResponse sets Content-Length automatically from the file
    )
```

**Key points:**
- `FileResponse` (not `StreamingResponse`) — it sets `Content-Length` from `os.path.getsize()`
- `filename=` parameter sets `Content-Disposition: attachment; filename="markflow.log"`
- `media_type="application/octet-stream"` forces download instead of browser display
- Size guard prevents attempting to download a 4GB file

### 2.3 If the endpoint MUST use StreamingResponse (e.g., for zipped output)

If the download zips multiple files or generates content on-the-fly, `StreamingResponse` is correct but MUST include `Content-Length` if the size is known, or use chunked transfer encoding properly:

```python
from fastapi.responses import StreamingResponse
import io, zipfile, os

@router.get("/api/settings/download-logs-zip")
async def download_logs_zip():
    # Build zip in memory
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for log_file in Path("logs").glob("*.log*"):
            zf.write(log_file, log_file.name)
    
    buffer.seek(0)
    size = buffer.getbuffer().nbytes
    
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="markflow-logs.zip"',
            "Content-Length": str(size),  # CRITICAL — without this, browser can't show progress
        },
    )
```

### 2.4 Frontend fix — don't use fetch() for file downloads

Search the settings HTML/JS for the download trigger. If it uses `fetch()` + blob URL, that's likely the loop source — `fetch` can silently retry on network hiccups, and blob URL creation in a `.then()` chain can re-trigger.

**Replace fetch-based download with a direct link or window.location:**

```javascript
// ❌ BAD — fetch-based download (prone to retry loops)
async function downloadLogs() {
    const response = await fetch('/api/settings/download-logs');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'markflow.log';
    a.click();
    URL.revokeObjectURL(url);
}

// ✅ GOOD — direct navigation (browser handles download natively)
function downloadLogs() {
    window.location.href = '/api/settings/download-logs';
}

// ✅ ALSO GOOD — anchor tag in HTML (simplest)
// <a href="/api/settings/download-logs" download class="btn">Download Logs</a>
```

**Why this fixes the loop:**
- `window.location.href` or `<a>` lets the browser's native download manager handle the transfer
- The browser respects `Content-Length` and `Content-Disposition` headers properly
- No JS retry logic, no blob intermediary, no re-triggering

### 2.5 Check for other download buttons on /settings

```bash
grep -n "download\|Download" static/settings.html
```

Apply the same fix to ALL download triggers on the page — not just the first one found.

### 2.6 Check for service worker or fetch interceptor

```bash
grep -rn "serviceWorker\|ServiceWorker\|navigator.serviceWorker" static/
grep -rn "addEventListener.*fetch" static/
```

If there's a service worker intercepting fetch requests and retrying, that could also cause the loop. If found, ensure the service worker passes through download requests without interception.

---

## 3. Test Checklist

### Log rotation tests

- [ ] Start the container. Verify `logs/` directory is created.
- [ ] `grep -rn "FileHandler" --include="*.py" | grep -v Rotating | grep -v test_ | grep -v __pycache__` returns nothing
- [ ] Set `LOG_MAX_SIZE_MB=1` (1MB for testing). Run a bulk conversion. Verify that `markflow.log.1`, `markflow.log.2` etc. appear when the log exceeds 1MB.
- [ ] Verify old rotated files are deleted when `backupCount` is exceeded
- [ ] Reset `LOG_MAX_SIZE_MB` to default (50) or remove the env var

### Download fix tests

- [ ] Click every download button on `/settings` — each file downloads completely and only once
- [ ] Downloaded file size matches the file size on disk inside the container
- [ ] No repeated download attempts visible in browser download manager
- [ ] Download a log file > 10MB — completes without restart
- [ ] Check browser Network tab — download request returns 200 with `Content-Length` header present
- [ ] Check `Content-Disposition` header includes `attachment; filename=...`

---

## 4. Files Likely Modified

Based on the project structure, these are the files most likely touched:

| File | Change |
|------|--------|
| `core/logging_config.py` | `FileHandler` → `RotatingFileHandler` with size caps |
| `main.py` or `app.py` | Ensure `logs/` dir creation at startup (if not in logging_config) |
| `api/routes/settings.py` | Fix download endpoint — `FileResponse` with proper headers + size guard |
| `static/settings.html` | Replace `fetch()`-based download with `window.location.href` or `<a>` tag |
| `docker-compose.yml` | Document `LOG_MAX_SIZE_MB`, `DEBUG_LOG_MAX_SIZE_MB`, `LOG_BACKUP_COUNT` env vars |
| `CLAUDE.md` | Bump patch version, document the fix under completed work |

**Verify actual filenames** by running `find . -name "*.py" -path "*/api/*" | head -20` and `ls static/` before editing. The table above is based on the expected project structure — actual names may differ.

---

## 5. CLAUDE.md Update

After both fixes are verified, update CLAUDE.md:

- Bump the patch version
- Under completed work, add:
  - `Log rotation: RotatingFileHandler on all log files (50MB main, 100MB debug, configurable via env vars)`
  - `Settings download fix: Replaced fetch-blob download pattern with direct FileResponse + window.location to eliminate download restart loop`
- Under known issues / gotchas, add:
  - `Log files: Never use bare FileHandler — always RotatingFileHandler. Default caps: 50MB main, 100MB debug.`
  - `File downloads: Never use fetch() + blob for file downloads — use window.location.href or <a> tags so the browser's native download manager handles the transfer.`
