"""
MCP connection info endpoint for the settings UI.

GET /api/mcp/connection-info — Returns MCP server URL and status.
"""

import os
import socket

import httpx
import structlog
from fastapi import APIRouter

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/connection-info")
async def mcp_connection_info():
    """Return MCP server connection details for the settings UI."""
    mcp_port = int(os.getenv("MCP_PORT", "8001"))
    auth_token = os.getenv("MCP_AUTH_TOKEN", "")

    # Try to get local IP
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "localhost"

    # Build URL
    base_url = f"http://{local_ip}:{mcp_port}/mcp"
    if auth_token:
        base_url += f"?token={auth_token}"

    # Check if MCP server is running
    mcp_running = False
    tool_count = 7  # We know our tool count statically
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://localhost:{mcp_port}/health")
            mcp_running = resp.status_code == 200
    except Exception:
        # MCP server might not have a /health endpoint; try SSE endpoint
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"http://localhost:{mcp_port}/sse")
                mcp_running = resp.status_code in (200, 405)
        except Exception:
            pass

    return {
        "mcp_url": base_url,
        "mcp_running": mcp_running,
        "tool_count": tool_count,
        "auth_required": bool(auth_token),
    }
