# MarkFlow — Default Log Level Environment Variable Patch

**Scope:** Tiny patch. Add `DEFAULT_LOG_LEVEL` env var support so the log level can be set
at container start without touching the UI.

**Prerequisite:** v0.12.0 codebase, CLAUDE.md loaded

---

## 0. Diagnose First

```bash
# Find where log level is initialized/defaulted
grep -rn 'log_level\|LOG_LEVEL\|normal.*level\|developer.*level' core/logging_config.py core/preferences.py 2>/dev/null
grep -rn 'log_level' core/ --include='*.py' | head -20

# Find the preferences init or default
grep -rn 'default.*normal\|log_level.*normal' core/ --include='*.py'

# Check docker-compose.yml environment section
grep -n 'environment\|MOUNTED_DRIVES\|MCP_AUTH_TOKEN\|SECRET_KEY' docker-compose.yml
```

**STOP.** Report findings before editing.

---

## 1. Backend: Read `DEFAULT_LOG_LEVEL` env var

**File:** `core/logging_config.py` (or wherever the log level is initialized at startup)

At the point where the log level is first set (likely to `"normal"` as default), replace the
hardcoded default with an env var read:

```python
import os

DEFAULT_LOG_LEVEL = os.getenv("DEFAULT_LOG_LEVEL", "normal")
```

Then use `DEFAULT_LOG_LEVEL` wherever `"normal"` was the hardcoded startup default.

If the log level is stored in the preferences DB table and loaded at startup, the env var
should override the DB value only on first boot (or always — your call). The simplest approach:
read the env var, and if it's set to something other than `"normal"`, apply it at startup
regardless of what's in the DB:

```python
env_level = os.getenv("DEFAULT_LOG_LEVEL", "").strip().lower()
if env_level in ("normal", "elevated", "developer"):
    # Apply this level at startup
    await set_log_level(env_level)
```

This goes in the lifespan/startup function in `main.py` or wherever logging is configured
during app init.

---

## 2. Docker Compose: Add the env var

**File:** `docker-compose.yml`

In the `markflow` service `environment:` section, add:

```yaml
environment:
  # ... existing vars ...
  DEFAULT_LOG_LEVEL: developer
```

---

## 3. Reset script: Ensure it survives rebuilds

**File:** `reset-markflow.sh` (on the Proxmox VM at `~/reset-markflow.sh`)

After the existing `sed` commands that patch paths, add:

```bash
# Set developer logging by default on test VM
if ! grep -q 'DEFAULT_LOG_LEVEL' docker-compose.yml; then
    sed -i '/environment:/a\      DEFAULT_LOG_LEVEL: developer' docker-compose.yml
fi
```

---

## 4. Verify

```bash
docker compose up -d
sleep 5
docker logs markflow-markflow-1 --tail 20 2>&1 | grep -i 'log_level\|level.*developer'
```

Should see the log level set to `developer` at startup without needing to toggle it in the UI.

---

## Done Criteria

- [ ] App starts with developer-level logging when `DEFAULT_LOG_LEVEL=developer` is set
- [ ] App starts with normal logging when the env var is absent or set to `normal`
- [ ] `reset-markflow.sh` injects the env var after `git pull`
- [ ] No code changes needed on the Settings page — the UI toggle still works and overrides
