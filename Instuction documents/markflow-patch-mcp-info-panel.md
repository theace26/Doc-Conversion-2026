# MarkFlow Patch: Fix MCP Info Panel URL

**Version:** v0.12.2 (minor UI fix)
**Priority:** Low — cosmetic, but causes user confusion
**Estimated time:** 5 minutes

---

## Problem

The MCP integration panel in MarkFlow's Settings page displays:
```
http://172.20.0.3:8001/mcp
```

Two issues:
1. **Wrong IP** — `172.20.0.3` is Docker's internal bridge network IP, unreachable from outside the container
2. **Wrong path** — the FastMCP SSE endpoint is `/sse`, not `/mcp`

This misleads users trying to connect Claude Desktop, Claude Code, or Claude.ai.

---

## Diagnostic (run first)

```bash
# Find where the MCP URL is rendered in the UI
docker exec doc-conversion-2026-markflow-1 grep -rn "172.20" /app/ --include="*.py" --include="*.html" --include="*.js" 2>/dev/null
docker exec doc-conversion-2026-markflow-1 grep -rn "/mcp" /app/ --include="*.html" --include="*.js" 2>/dev/null | grep -v node_modules | grep -v __pycache__

# Also check if it's dynamically generated from config
docker exec doc-conversion-2026-markflow-1 grep -rn "mcp.*url\|mcp.*endpoint\|MCP_SERVER_URL\|MCP_HOST" /app/ --include="*.py" --include="*.env" 2>/dev/null
```

Report findings before proceeding.

---

## Fix

Based on diagnostics, apply ONE of the following approaches:

### Approach A: If URL is hardcoded in a template (likely `templates/settings.html`)

Find the line rendering the MCP Server URL and replace it with a dynamic value that uses the request's host, or a sensible default:

**In the Python route** (likely `routes/settings.py` or `main.py`):
```python
# Add to the template context for the settings page
import os

mcp_port = os.getenv("MCP_PORT", "8001")
mcp_display_url = f"http://localhost:{mcp_port}/sse"
# Pass mcp_display_url to the template
```

**In the HTML template**, replace the hardcoded URL with:
```html
<input type="text" readonly value="{{ mcp_display_url }}" />
```

### Approach B: If URL is generated from container hostname in Python

Find where the URL is constructed (likely using `socket.gethostname()` or similar) and replace with:
```python
# OLD (something like):
# mcp_url = f"http://{hostname}:{port}/mcp"

# NEW:
mcp_url = f"http://localhost:{port}/sse"
```

### Approach C: If it's in a JS file

Find and replace the URL string directly:
```javascript
// OLD:
// const mcpUrl = `http://${window.location.hostname}:8001/mcp`;
// or hardcoded: "http://172.20.0.3:8001/mcp"

// NEW:
const mcpUrl = "http://localhost:8001/sse";
```

---

## Additional improvement (optional)

Update the setup instructions text in the same panel to show all three connection methods:

```html
<h4>Connection Methods</h4>

<p><strong>Claude Code (recommended):</strong></p>
<pre>claude mcp add markflow --transport sse http://localhost:8001/sse</pre>

<p><strong>Claude Desktop</strong> — add to claude_desktop_config.json:</p>
<pre>{
  "mcpServers": {
    "markflow": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8001/sse"]
    }
  }
}</pre>

<p><strong>Claude.ai (web)</strong> — requires tunnel (ngrok/Cloudflare):</p>
<ol>
  <li>Run: <code>ngrok http 8001</code></li>
  <li>Go to Claude.ai → Settings → Integrations → Add Integration</li>
  <li>Paste the ngrok URL + <code>/sse</code></li>
</ol>
```

---

## Verify

After applying the fix:
1. Rebuild container: `docker compose up -d --build markflow`
2. Open MarkFlow Settings page
3. Confirm the MCP panel shows `http://localhost:8001/sse`
4. Confirm the setup instructions are accurate

---

## CLAUDE.md update

Add to the v0.12.2 section:
```
- Fixed MCP info panel: corrected endpoint from /mcp to /sse, replaced Docker-internal IP with localhost
```
