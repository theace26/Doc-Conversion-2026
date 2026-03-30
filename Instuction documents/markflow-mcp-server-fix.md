# MarkFlow Patch — MCP Server Not Reachable

**Scope:** 1 file, 1 line change  
**Priority:** Quick fix — MCP container is up but not accepting connections

---

## Problem

The MCP server container (`markflow-mcp`) is running but returns empty replies on all
endpoints. Two root causes:

1. **Port mismatch:** `main()` reads `MCP_PORT` (default 8001) but `mcp.run(transport="sse")`
   starts Uvicorn on its own default port (8000). The port variable is never passed through.
2. **Bound to 127.0.0.1:** Uvicorn binds to localhost inside the container. Docker port
   mapping (0.0.0.0:8001→8001) can't route traffic to 127.0.0.1 inside the container.

Evidence from `docker logs`:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Should be:
```
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
```

---

## Diagnostic

```bash
grep -n 'mcp.run\|transport' mcp_server/server.py
docker logs doc-conversion-2026-markflow-mcp-1 --tail 5 2>/dev/null || \
docker logs markflow-markflow-mcp-1 --tail 5
```

Confirm you see `mcp.run(transport="sse")` with no `host` or `port` args, and Uvicorn
on `127.0.0.1:8000`.

---

## Fix

In `mcp_server/server.py`, find the `main()` function (bottom of file). Change the
`mcp.run()` call:

```python
# BEFORE:
    mcp.run(transport="sse")

# AFTER:
    mcp.run(transport="sse", host="0.0.0.0", port=port)
```

That's it. One line.

**If `mcp.run()` does not accept `host` and `port` kwargs** (depends on the FastMCP
version), check what it does accept:

```python
# Diagnostic — run inside the container:
docker exec <container> python -c "from mcp.server.fastmcp import FastMCP; help(FastMCP.run)"
```

Alternative approaches if kwargs aren't supported:

```python
# Option A: Environment variables that Uvicorn reads
os.environ["UVICORN_HOST"] = "0.0.0.0"
os.environ["UVICORN_PORT"] = str(port)
mcp.run(transport="sse")

# Option B: Direct uvicorn call (bypassing mcp.run)
import uvicorn
uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port)
```

Try the kwargs first — it's the cleanest.

---

## Verify

```bash
# Rebuild
docker compose up -d --build markflow-mcp

# Wait for startup
sleep 5

# Check logs — should show 0.0.0.0:8001
docker logs <container> --tail 5

# Test from host
curl http://localhost:8001/sse
# Should get an SSE response (event stream), not empty reply
```

---

## Update CLAUDE.md

Add to gotchas:

```markdown
- **MCP server binding**: `mcp.run()` must pass `host="0.0.0.0", port=port` explicitly.
  Without these, FastMCP defaults to 127.0.0.1:8000 which is unreachable from outside
  the Docker container.
```

---

## Done Criteria

- [ ] `mcp.run()` call passes `host="0.0.0.0"` and `port=port`
- [ ] `docker logs` shows `Uvicorn running on http://0.0.0.0:8001`
- [ ] `curl http://localhost:8001/sse` returns an SSE event stream (not empty reply)
- [ ] MarkFlow Settings page shows "MCP server connected" (or similar)
- [ ] CLAUDE.md gotchas updated
- [ ] Git commit
