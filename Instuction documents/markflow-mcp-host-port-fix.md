# MarkFlow Patch — MCP Server Host/Port Binding Fix

**Scope:** 1 file, ~3 lines changed  
**Priority:** Blocking — MCP container crash-looping

---

## Problem

The MCP server container is crash-looping. `FastMCP.run()` does NOT accept `host` or
`port` keyword arguments in the installed version. The current code either:

- (a) Calls `mcp.run(transport="sse")` with no host/port → Uvicorn defaults to
  `127.0.0.1:8000`, which is unreachable from outside the container and on the wrong port.
- (b) Calls `mcp.run(transport="sse", host="0.0.0.0", port=port)` → crashes with
  `TypeError: FastMCP.run() got an unexpected keyword argument 'host'`

**Evidence:**
```
TypeError: FastMCP.run() got an unexpected keyword argument 'host'
```

---

## Diagnostic

```bash
grep -n 'mcp.run' mcp_server/server.py
docker logs doc-conversion-2026-markflow-mcp-1 --tail 10 2>/dev/null || \
docker logs markflow-markflow-mcp-1 --tail 10
```

---

## Fix

In `mcp_server/server.py`, find the `main()` function at the bottom of the file.

Replace the `mcp.run(...)` call and the lines immediately before it with this:

```python
    log.info("mcp_server_start", port=port, tools=10)

    # FastMCP.run() doesn't accept host/port kwargs in this version.
    # Set via environment variables that Uvicorn reads at startup.
    os.environ["UVICORN_HOST"] = "0.0.0.0"
    os.environ["UVICORN_PORT"] = str(port)
    mcp.run(transport="sse")
```

**Do NOT pass `host=` or `port=` to `mcp.run()`.** That crashes the server.

**If the UVICORN env vars don't work** (Uvicorn still shows `127.0.0.1:8000` in logs),
use direct uvicorn invocation instead:

```python
    log.info("mcp_server_start", port=port, tools=10)

    # Direct uvicorn call — bypass mcp.run() entirely
    import uvicorn
    app = mcp.sse_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
```

Try the env var approach first. Only fall back to `uvicorn.run()` if logs still show
the wrong host/port.

---

## Verify

```bash
# Rebuild
docker compose up -d --build markflow-mcp

# Wait for startup
sleep 5

# Check logs — MUST show 0.0.0.0:8001, not 127.0.0.1:8000
docker logs doc-conversion-2026-markflow-mcp-1 --tail 5 2>/dev/null || \
docker logs markflow-markflow-mcp-1 --tail 5

# Test connectivity from host
curl http://localhost:8001/sse
# Expected: SSE event stream (text/event-stream), NOT empty reply or connection refused
```

---

## Update CLAUDE.md

Add to gotchas:

```markdown
- **MCP server binding**: `FastMCP.run()` does NOT accept `host` or `port` kwargs.
  Set `os.environ["UVICORN_HOST"] = "0.0.0.0"` and `os.environ["UVICORN_PORT"]`
  before calling `mcp.run(transport="sse")`. Without this, Uvicorn defaults to
  127.0.0.1:8000 which is unreachable from outside the Docker container.
```

---

## Done Criteria

- [ ] `mcp.run()` called with ONLY `transport="sse"` — no `host` or `port` kwargs
- [ ] `os.environ["UVICORN_HOST"]` set to `"0.0.0.0"` before `mcp.run()`
- [ ] `os.environ["UVICORN_PORT"]` set to `str(port)` before `mcp.run()`
- [ ] Container stays up (no crash loop)
- [ ] `docker logs` shows `Uvicorn running on http://0.0.0.0:8001`
- [ ] `curl http://localhost:8001/sse` returns SSE stream
- [ ] CLAUDE.md gotchas updated
- [ ] Git commit
