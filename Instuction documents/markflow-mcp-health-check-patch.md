# MarkFlow Patch: MCP Server Health Check Endpoint

**Patch ID:** mcp-health-check
**Target Version:** Current (apply on top of latest `main`)
**Priority:** High — blocks MCP status detection in the UI
**Estimated Complexity:** Low (< 20 lines changed)

---

## Problem

The MarkFlow UI's "Claude Integration (MCP)" panel pings `GET /health` on the MCP server to determine connection status. The MCP server (`markflow-mcp` container) is running and serving SSE connections correctly, but `FastMCP.sse_app()` does not include a `/health` endpoint. The health check returns `404 Not Found`, causing the UI to display **"MCP server not detected"** even though the server is fully operational.

**Evidence from container logs:**
```
INFO:     172.20.0.1:53014 - "GET /sse HTTP/1.1" 200 OK
INFO:     172.20.0.3:37482 - "GET /health HTTP/1.1" 404 Not Found
```

The MCP container is healthy — it just needs to answer the health check.

---

## Pre-Patch Diagnostics

Run these to confirm the issue before making changes. All commands target the **Proxmox VM** (`union`, `192.168.1.208`). If running on Windows dev, substitute container name `doc-conversion-2026-markflow-mcp-1`.

```bash
# 1. Confirm MCP container is running
docker ps --filter "name=mcp" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 2. Confirm /health returns 404
docker exec markflow-markflow-1 curl -s -o /dev/null -w "%{http_code}" http://markflow-mcp:8001/health
# Expected: 404

# 3. Confirm /sse is working (should return 200 or hang on SSE stream)
docker exec markflow-markflow-1 curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://markflow-mcp:8001/sse
# Expected: 200

# 4. Verify current server.py main() function
grep -n "sse_app\|uvicorn.run\|def main" mcp_server/server.py
```

---

## Fix 1: Add `/health` endpoint to MCP server

**File:** `mcp_server/server.py`

### Step 1a: Add imports at the top of the file

Find the existing import block near the top of the file. After the last import line (before any module-level code like `log = structlog.get_logger()`), add:

```python
from starlette.responses import JSONResponse
from starlette.routing import Route
```

### Step 1b: Modify the `main()` function

Find the `main()` function. Locate the line:

```python
    uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)
```

Replace it with:

```python
    # Build the SSE app from FastMCP
    app = mcp.sse_app()

    # Add health check endpoint (FastMCP doesn't include one by default)
    def health_check(request):
        return JSONResponse({
            "status": "ok",
            "service": "markflow-mcp",
            "port": port,
        })

    app.routes.append(Route("/health", health_check))

    uvicorn.run(app, host="0.0.0.0", port=port)
```

---

## Fix 2: Verify the UI health check URL is correct

The main MarkFlow app checks MCP status from the **browser** (client-side JS), which means it uses `localhost:8001`, not the Docker internal hostname. This is correct because docker-compose exposes `8001:8001` on the host.

However, we should also verify the **server-side** MCP health check (if the main app does one internally). Check for any backend code that pings the MCP server:

```bash
grep -rn "MCP_HOST\|markflow-mcp\|8001\|mcp.*health" api/ core/ static/ templates/ --include="*.py" --include="*.js" --include="*.html" | head -20
```

If the main app's backend pings MCP health using `localhost:8001`, that's wrong inside Docker (containers are isolated). It should use the Docker service name: `http://markflow-mcp:8001/health`. The environment variable `MCP_HOST=markflow-mcp` and `MCP_PORT=8001` are already set in docker-compose.yml for this purpose.

**If you find a hardcoded `localhost:8001` in any Python file**, replace it with:
```python
mcp_host = os.getenv("MCP_HOST", "localhost")
mcp_port = os.getenv("MCP_PORT", "8001")
mcp_url = f"http://{mcp_host}:{mcp_port}"
```

**If the health check is only in browser-side JavaScript** (e.g., `static/js/*.js` or inline in templates), then `localhost:8001` is correct — the browser runs on the host machine, not inside Docker. No change needed in that case.

---

## Post-Patch Verification

```bash
# 1. Rebuild only the MCP container
docker compose up -d --build markflow-mcp

# 2. Wait for it to start
sleep 5

# 3. Confirm /health now returns 200
docker exec markflow-markflow-1 curl -s http://markflow-mcp:8001/health
# Expected: {"status":"ok","service":"markflow-mcp","port":8001}

# 4. Confirm /sse still works
docker exec markflow-markflow-1 curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://markflow-mcp:8001/sse
# Expected: 200

# 5. From the host (outside Docker), test the exposed port
curl -s http://localhost:8001/health
# Expected: {"status":"ok","service":"markflow-mcp","port":8001}

# 6. Open the MarkFlow UI in browser → navigate to Settings or MCP panel
# Status should now show MCP server as connected/detected
```

---

## CLAUDE.md Update

Add to the **Resolved Bugs** or **Changelog** section:

```
- **MCP health check 404** — Added `/health` endpoint to `mcp_server/server.py`.
  FastMCP's `sse_app()` does not include a health route by default. The main app's
  UI was correctly pinging `/health` but getting 404, showing "MCP server not detected"
  even though the server was running. Fixed by appending a Starlette Route to the
  SSE app before passing it to uvicorn. (mcp-health-check patch)
```

---

## Notes

- This patch does **not** modify the main MarkFlow app, only the MCP server.
- `starlette` is already a dependency (FastAPI depends on it), so no new packages are needed.
- The health endpoint is intentionally simple. If you later want to include DB connectivity or Meilisearch reachability in the health response, extend the `health_check` function to query those and return degraded status accordingly.
- On the Proxmox VM, remember to `git pull` and run `reset-markflow.sh` to pick up changes after pushing from the Windows dev machine.
